"""日野の公式整備PDFを月次確認し、変更資料を既存の確認待ちへ登録する。"""
import hashlib
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

ROOT = "https://www.hino.co.jp/ts/vehicle_maintenance/"
MAX_BYTES = 10 * 1024 * 1024


def next_month(now):
    return datetime(now.year + (now.month == 12), now.month % 12 + 1, 1)


def allowed_url(url):
    p = urllib.parse.urlsplit(url)
    return (
        p.scheme == "https" and p.hostname == "www.hino.co.jp"
        and p.port in (None, 443) and not p.username and not p.password
        and p.path.startswith("/ts/vehicle_maintenance/")
        and ".." not in urllib.parse.unquote(p.path)
        and not p.query and not p.fragment
    )


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise ValueError("公開資料の転送先が許可範囲外です。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_bytes(url, limit=MAX_BYTES):
    if not allowed_url(url):
        raise ValueError("公開資料のURLが許可範囲外です。")
    req = urllib.request.Request(url, headers={
        "User-Agent": "DKSS-Maintenance-Knowledge/1.0",
        "Accept-Encoding": "identity",
    })
    opener = urllib.request.build_opener(OfficialRedirect())
    with opener.open(req, timeout=30) as response:
        if not allowed_url(response.geturl()):
            raise ValueError("公開資料の取得先が許可範囲外です。")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("公開資料が容量制限を超えています。")
    return data


def discover_hino_documents():
    data = json.loads(fetch_bytes(ROOT + "json/data.json", 2 * 1024 * 1024).decode("utf-8-sig"))
    if not isinstance(data, list) or not 1 <= len(data) <= 2000:
        raise ValueError("公式資料一覧の形式が変わっています。")
    found = {}
    for item in data:
        if not isinstance(item, dict) or str(item.get("disabled") or "").strip():
            continue
        if not any(str(item.get(key)) == "1" for key in ("profia", "ranger", "dutro")):
            continue
        name = str(item.get("pdf") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.pdf", name):
            continue
        found[ROOT + "pdf/" + name] = str(item.get("text") or name)[:240]
    if not found:
        raise ValueError("トラック向けの公式PDF一覧を確認できません。")
    # 一覧の上部にある共通資料。リンクが現存するものだけ対象にする。
    page = fetch_bytes(ROOT, 2 * 1024 * 1024).decode("utf-8", errors="replace")
    common = {
        "20221021_1.pdf": "定期メンテナンスのご案内（トラック）",
        "202506.pdf": "エンジンオイルメンテナンスの重要性",
        "202506_checksheet.pdf": "エンジンオイル量・日常点検用チェックシート",
    }
    for name, title in common.items():
        if "./pdf/" + name in page:
            found.setdefault(ROOT + "pdf/" + name, title)
    return found


def register_public_knowledge(app, db, Vehicle, Company, Knowledge):
    class PublicKnowledgeCatalog(db.Model):
        __tablename__ = "public_knowledge_catalog"
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, unique=True)
        next_check = db.Column(db.DateTime, nullable=False)
        last_checked = db.Column(db.DateTime)
        lease_token = db.Column(db.String(36))
        lease_until = db.Column(db.DateTime)
        last_error = db.Column(db.String(200), default="")

    class PublicKnowledgeFile(db.Model):
        __tablename__ = "public_knowledge_file"
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        url = db.Column(db.String(500), nullable=False)
        title = db.Column(db.String(240), nullable=False)
        priority = db.Column(db.Integer, nullable=False, default=0)
        available = db.Column(db.Boolean, nullable=False, default=True)
        next_check = db.Column(db.DateTime, nullable=False)
        last_checked = db.Column(db.DateTime)
        checksum = db.Column(db.String(64), default="")
        document_id = db.Column(db.String(36))
        last_import_month = db.Column(db.String(7))
        status = db.Column(db.String(30), nullable=False, default="pending")
        last_error = db.Column(db.String(200), default="")
        __table_args__ = (db.UniqueConstraint("company_code", "url"),)

    def target_companies():
        rows = db.session.query(Vehicle.company_code, Vehicle.manufacturer).join(
            Company, Company.company_code == Vehicle.company_code,
        ).filter(Vehicle.deleted.is_(False), Company.active.is_(True)).distinct().all()
        return sorted({company for company, maker in rows if unicodedata.normalize(
            "NFKC", str(maker or "")
        ).strip().casefold() in {"日野", "hino", "日野自動車", "日野自動車株式会社"}})

    def retire_document(company, document_id, reason, now):
        if not document_id:
            return
        Knowledge.query.filter(
            Knowledge.company_code == company,
            Knowledge.status == "active",
            Knowledge.source_reference.contains(f"[knowledge-document:{document_id}]"),
        ).update({
            "status": "retired", "retired_by": "public-knowledge-worker",
            "retired_at": now.strftime("%Y/%m/%d %H:%M"),
            "retirement_reason": reason,
        }, synchronize_session=False)

    def scan_catalog(catalog, now):
        found = discover_hino_documents()
        existing = {row.url: row for row in PublicKnowledgeFile.query.filter_by(
            company_code=catalog.company_code,
        ).all()}
        previously_available = sum(row.available for row in existing.values())
        if previously_available and len(found) < previously_available * 0.8:
            raise ValueError("公式一覧が急減したため、掲載終了の自動反映を保留しました。")
        for priority, (url, title) in enumerate(found.items()):
            row = existing.get(url)
            if row is None:
                row = PublicKnowledgeFile(company_code=catalog.company_code,
                    url=url, title=title, next_check=now, priority=priority)
                db.session.add(row)
            else:
                row.title = title
                row.priority = priority
                row.available = True
        for url, row in existing.items():
            if url not in found and row.available:
                row.available = False
                row.status = "unlisted"
                retire_document(catalog.company_code, row.document_id,
                    "公式資料一覧で掲載を確認できないため、再確認まで分析への利用を停止。", now)
        catalog.last_checked = now
        catalog.next_check = next_month(now)
        catalog.last_error = ""
        db.session.commit()
        return f"公式一覧 {len(found)}件を確認"

    def scan_file(row, now):
        data = fetch_bytes(row.url)
        if not data.startswith(b"%PDF-"):
            raise ValueError("取得した資料がPDFではありません。")
        checksum = hashlib.sha256(data).hexdigest()
        if checksum == row.checksum:
            row.status = "unchanged"
        else:
            month = now.strftime("%Y-%m")
            limit = max(0, min(100, int(os.environ.get("PUBLIC_KNOWLEDGE_MONTHLY_LIMIT", "10"))))
            imported = PublicKnowledgeFile.query.filter_by(
                company_code=row.company_code, last_import_month=month,
            ).count()
            if imported >= limit:
                if row.document_id:
                    retire_document(row.company_code, row.document_id,
                        "公式原本の変更を検出。新版読取りまで旧版知識の利用を停止。", now)
                row.status = "monthly_limit"
                row.next_check = next_month(now)
                row.last_checked = now
                db.session.commit()
                return "月の読取り上限に到達。残りは次月に繰越"
            old_document_id = row.document_id
            store = app.extensions["maintenance_knowledge_import"]["store_public_document"]
            filename = row.title[:100] + "_" + row.url.rsplit("/", 1)[-1]
            document_id = store(row.company_code, data, filename, row.url, "日野")
            # 別版の採用済み知識は、新版の確認が済むまで利用を止める。
            if old_document_id and old_document_id != document_id:
                retire_document(row.company_code, old_document_id,
                    "公式原本が更新されたため、新版の確認まで旧版知識の利用を停止。", now)
            row.document_id = document_id
            row.checksum = checksum
            row.last_import_month = month
            row.status = "review"
        row.last_checked = now
        row.next_check = next_month(now)
        row.last_error = ""
        db.session.commit()
        return "原本の変更なし" if row.status == "unchanged" else "資料を取込・確認待ちへ登録"

    def tick(now=None):
        now = now or datetime.now(ZoneInfo("Asia/Tokyo")).replace(tzinfo=None)
        if os.environ.get("PUBLIC_KNOWLEDGE_ENABLED", "1") != "1":
            return "公開資料の自動確認は停止中"
        for company in target_companies():
            catalog = PublicKnowledgeCatalog.query.filter_by(company_code=company).first()
            if catalog is None:
                db.session.add(PublicKnowledgeCatalog(company_code=company, next_check=now))
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                catalog = PublicKnowledgeCatalog.query.filter_by(company_code=company).one()
            token = str(uuid4())
            claimed = PublicKnowledgeCatalog.query.filter(
                PublicKnowledgeCatalog.id == catalog.id,
                db.or_(PublicKnowledgeCatalog.lease_until.is_(None), PublicKnowledgeCatalog.lease_until <= now),
            ).update({"lease_token": token, "lease_until": now + timedelta(minutes=10)}, synchronize_session=False)
            db.session.commit()
            if not claimed:
                continue
            catalog = db.session.get(PublicKnowledgeCatalog, catalog.id)
            row = None
            result = None
            try:
                if catalog.next_check <= now:
                    result = scan_catalog(catalog, now)
                else:
                    row = PublicKnowledgeFile.query.filter(
                        PublicKnowledgeFile.company_code == company,
                        PublicKnowledgeFile.available.is_(True),
                        PublicKnowledgeFile.next_check <= now,
                    ).order_by(PublicKnowledgeFile.priority, PublicKnowledgeFile.id).first()
                    if row is not None:
                        result = scan_file(row, now)
            except Exception as error:
                db.session.rollback()
                # APIキーや本文をログに残さず、失敗した種類だけ表示する。
                code = type(error).__name__
                if row is None:
                    catalog.next_check = now + timedelta(days=1)
                    catalog.last_error = code
                else:
                    row.next_check = now + timedelta(days=1)
                    row.last_error = code
                    row.status = "error"
                db.session.commit()
                result = f"取得・読取り失敗（{code}）。翌日再試行"
                app.logger.warning("公開整備資料: %s", result)
            finally:
                PublicKnowledgeCatalog.query.filter_by(id=catalog.id, lease_token=token).update(
                    {"lease_token": None, "lease_until": None}, synchronize_session=False)
                db.session.commit()
            if result is not None:
                return result
        return None

    @app.cli.command("public-knowledge-tick")
    def public_knowledge_tick():
        print(tick() or "公開資料: 次の月次確認を待機中", flush=True)

    @app.cli.command("public-knowledge-status")
    def public_knowledge_status():
        for company in target_companies():
            catalog = PublicKnowledgeCatalog.query.filter_by(company_code=company).first()
            states = db.session.query(PublicKnowledgeFile.status, db.func.count(PublicKnowledgeFile.id)).filter_by(
                company_code=company,
            ).group_by(PublicKnowledgeFile.status).all()
            print(f"会社 {company}: 次回一覧確認 {catalog.next_check if catalog else '未実施'} / {dict(states)}", flush=True)
            errors = PublicKnowledgeFile.query.filter_by(company_code=company, status="error").limit(5).all()
            for row in errors:
                print(f"  {row.title}: {row.last_error}", flush=True)

    app.extensions["public_maintenance_knowledge"] = {
        "tick": tick, "catalog_model": PublicKnowledgeCatalog, "file_model": PublicKnowledgeFile,
    }
    return tick
