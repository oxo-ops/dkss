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
MAX_BYTES = 32 * 1024 * 1024


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
    from dkss_app.public_maintenance_knowledge_models import get_models
    PublicKnowledgeCatalog, PublicKnowledgeFile, = get_models(db)


    def target_vehicle_scopes():
        rows = db.session.query(
            Vehicle.company_code,
            Vehicle.manufacturer,
            Vehicle.model_code,
        ).join(
            Company, Company.company_code == Vehicle.company_code,
        ).filter(
            Vehicle.deleted.is_(False),
            Company.active.is_(True),
        ).distinct().all()
        scopes = {}
        aliases = {
            "hino", "\u65e5\u91ce",
            "\u65e5\u91ce\u81ea\u52d5\u8eca",
            "\u65e5\u91ce\u81ea\u52d5\u8eca\u682a\u5f0f\u4f1a\u793e",
        }
        for company, manufacturer, model in rows:
            maker = unicodedata.normalize(
                "NFKC", str(manufacturer or "")
            ).strip().casefold()
            if maker not in aliases:
                continue
            normalized_model = unicodedata.normalize(
                "NFKC", str(model or "")
            ).strip().casefold()
            scopes.setdefault(company, set()).add(
                ("hino", normalized_model)
            )
        return {
            company: hashlib.sha256(json.dumps(
                sorted(values), ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            for company, values in scopes.items()
        }

    def target_companies():
        return sorted(target_vehicle_scopes())

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
                # 一覧からの掲載終了と、整備基準の廃止は区別する。
                # 掲載を確認できないだけでは既存の知識を廃止しない。
        catalog.last_checked = now
        catalog.next_check = now + timedelta(days=7)
        catalog.last_error = ""
        db.session.commit()
        return f"公式一覧 {len(found)}件を確認"

    def get_public_document_states(company_code, document_ids, *, now=None):
        """取得済み原本の状態を返す。知識の採用・廃止は行わない。"""
        import re

        if (
            not isinstance(company_code, str)
            or not company_code.strip()
            or not isinstance(document_ids, (list, tuple, set))
            or any(
                not isinstance(value, str)
                or not re.fullmatch(r"[a-f0-9-]{36}", value)
                for value in document_ids
            )
        ):
            raise ValueError("PUBLIC_DOCUMENT_LOOKUP_INVALID")

        ids = sorted(set(document_ids))
        if not ids:
            return {}

        checked_now = now
        if checked_now is None:
            checked_now = datetime.now(
                ZoneInfo("Asia/Tokyo")
            ).replace(tzinfo=None)
        elif checked_now.tzinfo is not None:
            checked_now = checked_now.astimezone(
                ZoneInfo("Asia/Tokyo")
            ).replace(tzinfo=None)

        states = {}
        rows = PublicKnowledgeFile.query.filter_by(
            company_code=company_code,
        ).filter(
            PublicKnowledgeFile.document_id.in_(ids),
        ).all()

        for row in rows:
            valid_checksum = (
                isinstance(row.checksum, str)
                and re.fullmatch(r"[a-f0-9]{64}", row.checksum)
                is not None
            )
            if not row.available:
                state = "unlisted"
            elif row.status not in {"review", "unchanged"}:
                state = "verification_pending"
            elif not valid_checksum:
                state = "checksum_missing"
            elif row.last_checked is None:
                state = "check_date_missing"
            elif row.last_checked > checked_now:
                state = "check_date_invalid"
            elif row.next_check is None or row.next_check < checked_now:
                state = "verification_due"
            else:
                state = "observed"

            states.setdefault(row.document_id, []).append({
                "public_file_id": row.id,
                "document_id": row.document_id,
                "company_code": row.company_code,
                "source_url": row.url,
                "document_checksum": row.checksum,
                "source_state": state,
                "file_status": row.status,
                "available": bool(row.available),
                "last_checked": (
                    row.last_checked.isoformat()
                    if row.last_checked else None
                ),
                "next_check": (
                    row.next_check.isoformat()
                    if row.next_check else None
                ),
                "checked_timezone": "Asia/Tokyo",
                "scope": "last_observed_public_document",
            })

        return states

    app.extensions["maintenance_knowledge_import"][
        "get_public_document_states"
    ] = get_public_document_states

    def scan_file(row, now):
        data = fetch_bytes(row.url)
        if not data.startswith(b"%PDF-"):
            raise ValueError("取得した資料がPDFではありません。")
        checksum = hashlib.sha256(data).hexdigest()
        # LEGACY_PUBLIC_RULE_REVISION_V1
        extension = app.extensions["maintenance_knowledge_import"]
        upgrade_enabled = os.environ.get("PUBLIC_KNOWLEDGE_UPGRADE_LEGACY", "0") == "1"
        needs_upgrade = extension.get("document_needs_rule_upgrade")
        upgrade_legacy = bool(
            upgrade_enabled and checksum == row.checksum
            and row.document_id and needs_upgrade
            and needs_upgrade(row.company_code, row.document_id)
        )
        if checksum == row.checksum and not upgrade_legacy:
            row.status = "unchanged"
        else:
            month = now.strftime("%Y-%m")
            limit = max(0, min(100, int(os.environ.get("PUBLIC_KNOWLEDGE_MONTHLY_LIMIT", "10"))))
            imported = PublicKnowledgeFile.query.filter_by(
                company_code=row.company_code, last_import_month=month,
            ).count()
            # LEGACY_RULE_MONTHLY_QUOTA_V1
            upgrade_counter = extension.get("count_rule_upgrades")
            if upgrade_enabled and not callable(upgrade_counter):
                raise ValueError("RULE_UPGRADE_QUOTA_COUNTER_UNAVAILABLE")
            if callable(upgrade_counter):
                imported += upgrade_counter(row.company_code, month)
            if imported >= limit:
                # 読取り上限への到達だけでは、既存の知識を廃止しない。
                # 新版の取得・検証が完了するまで旧版と原本を保持する。
                row.status = "monthly_limit"
                row.next_check = next_month(now)
                row.last_checked = now
                db.session.commit()
                return "月の読取り上限に到達。残りは次月に繰越"
            store = app.extensions["maintenance_knowledge_import"]["store_public_document"]
            filename = row.title[:100] + "_" + row.url.rsplit("/", 1)[-1]
            if upgrade_enabled:
                document_id = store(row.company_code, data, filename, row.url, "日野", upgrade_legacy=True)
            else:
                document_id = store(row.company_code, data, filename, row.url, "日野")
            # 新版の抽出候補を保存する。候補保存だけでは旧版を廃止しない。
            # 旧版との切替は、適用条件・改訂内容の検証後に行う。
            row.document_id = document_id
            row.checksum = checksum
            if not upgrade_legacy:
                row.last_import_month = month
            row.status = "review"
        row.last_checked = now
        row.next_check = now + timedelta(days=7)
        row.last_error = ""
        db.session.commit()
        return "原本の変更なし" if row.status == "unchanged" else "資料を取込・確認待ちへ登録"

    def tick(now=None):
        now = now or datetime.now(ZoneInfo("Asia/Tokyo")).replace(tzinfo=None)
        if os.environ.get("PUBLIC_KNOWLEDGE_ENABLED", "1") != "1":
            return "公開資料の自動確認は停止中"
        vehicle_scopes = target_vehicle_scopes()
        for company in sorted(vehicle_scopes):
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
                scope_hash = vehicle_scopes[company]
                scope_changed = catalog.requested_scope_hash != scope_hash
                weekly_due = (
                    not catalog.last_error
                    and catalog.last_checked is not None
                    and catalog.last_checked + timedelta(days=7) <= now
                )
                if scope_changed or weekly_due or catalog.next_check <= now:
                    if scope_changed:
                        catalog.requested_scope_hash = scope_hash
                        db.session.commit()
                    result = scan_catalog(catalog, now)
                else:
                    row = PublicKnowledgeFile.query.filter(
                        PublicKnowledgeFile.company_code == company,
                        PublicKnowledgeFile.available.is_(True),
                        db.or_(
                            PublicKnowledgeFile.next_check <= now,
                            db.and_(
                                PublicKnowledgeFile.status.in_(
                                    {"review", "unchanged"}
                                ),
                                PublicKnowledgeFile.last_checked
                                <= now - timedelta(days=7),
                            ),
                        ),
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
