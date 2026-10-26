"""Company-scoped vehicle combinations, separate from operating permissions."""
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import parse_qsl, urlencode, urlsplit

from flask import abort, current_app, flash, redirect, request, session, url_for
from sqlalchemy import inspect, or_
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

from .access import require_master_admin
from .audit import add_audit_log
from .extensions import db
from .models import Vehicle, VehicleCoupling
from .vehicle_readers import vehicle_number


def vehicle_text(vehicle):
    value = unicodedata.normalize("NFKC", f"{vehicle.type or ''} {vehicle.body_type or ''}").casefold()
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in value)


def coupling_role(vehicle):
    text = vehicle_text(vehicle)
    if any(word in text for word in ("トラクタ", "トレーラーヘッド", "トレーラヘッド", "tractor", "prime mover")):
        return "tractor"
    if any(word in text for word in ("トレーラ", "トレイラ", "被牽引", "被ケン引", "trailer")):
        return "trailer"
    if any(word in text for word in ("乗用", "セダン", "軽自動車", "suv", "passenger", "バス", "二輪", "フォークリフト", "大型特殊")):
        return None
    if any(word in text for word in ("トラック", "大型", "中型", "小型", "平ボディ", "平ボデー", "平車", "ウイング", "ウィング", "ダンプ", "タンク", "truck", "flatbed")):
        return "truck"
    return None


def pair_kind(first, second):
    """Return a directed pair; reject unsuitable roles and known subtype clashes."""
    first_role, second_role = coupling_role(first), coupling_role(second)
    if first_role == "trailer" and second_role in {"tractor", "truck"}:
        towing, trailer = second, first
    elif second_role == "trailer" and first_role in {"tractor", "truck"}:
        towing, trailer = first, second
    else:
        return None
    tow_text, trailer_text = vehicle_text(towing), vehicle_text(trailer)
    full = coupling_role(towing) == "truck" or "フル" in tow_text or "full" in tow_text
    trailer_full = "フル" in trailer_text or "full" in trailer_text
    trailer_semi = "セミ" in trailer_text or "semi" in trailer_text
    tow_semi = "セミ" in tow_text or "semi" in tow_text
    if (full and trailer_semi) or (tow_semi and trailer_full):
        return None
    return towing, trailer, "full" if full or trailer_full else "semi"


def schema_ready():
    # Existing deployments must run init-db explicitly; never run DDL on a GET.
    key = "vehicle_couplings_schema_ready"
    state = current_app.extensions["dkss"]
    if not state.get(key):
        state[key] = inspect(db.engine).has_table(VehicleCoupling.__tablename__)
    return state[key]


def label(vehicle):
    number = vehicle_number({key: getattr(vehicle, key) or "" for key in
                             ("plate_area", "plate_class", "plate_kana", "plate_number")})
    return number.strip() or vehicle.chassis_number or f"車両 {vehicle.id}"


def coupling_context(vehicle, vehicles):
    if vehicle is None:
        return {}
    role = coupling_role(vehicle)
    ready = schema_ready()
    by_id = {item.id: item for item in vehicles if item.company_code == vehicle.company_code}
    links = []
    if ready:
        rows = VehicleCoupling.query.filter_by(company_code=vehicle.company_code).filter(or_(
            VehicleCoupling.towing_vehicle_id == vehicle.id,
            VehicleCoupling.trailer_vehicle_id == vehicle.id,
        )).order_by(VehicleCoupling.id).all()
        for row in rows:
            peer_id = row.trailer_vehicle_id if row.towing_vehicle_id == vehicle.id else row.towing_vehicle_id
            peer = by_id.get(peer_id)
            if peer is not None:
                links.append({"id": row.id, "vehicle_id": peer.id, "label": label(peer),
                              "office": peer.office or "", "deleted": bool(peer.deleted)})
    linked_ids = {item["vehicle_id"] for item in links}
    candidates = []
    if role and not vehicle.deleted and require_master_admin() and ready:
        for peer in by_id.values():
            if peer.id == vehicle.id or peer.id in linked_ids or peer.deleted:
                continue
            pair = pair_kind(vehicle, peer)
            if pair is not None:
                candidates.append({"id": peer.id, "label": label(peer), "office": peer.office or "",
                                   "type": peer.type or peer.body_type or "", "chassis": peer.chassis_number or ""})
        candidates.sort(key=lambda item: (item["office"] != vehicle.office, item["office"], item["label"], item["id"]))
    return {"visible": bool(candidates or links), "ready": ready, "links": links,
            "can_edit": require_master_admin(), "can_add": bool(candidates),
            "candidates": candidates, "role": role,
            "button_label": "連結車両を設定"}


def current_vehicle(vehicle_record_id):
    return Vehicle.query.filter_by(id=vehicle_record_id, company_code=session.get("company_code")).first_or_404()


def require_edit_ready():
    if not require_master_admin():
        abort(403)
    if not schema_ready():
        abort(503, description="連結車両の登録準備が完了していません。管理者に連絡してください。")


def coupling_return_url(vehicle):
    value = request.form.get("return_to", "")
    if not value or len(value) > 2048 or any(c in value for c in ("\\", "\r", "\n")):
        return url_for("vehicle_karte", vehicle_record_id=vehicle.id)
    try:
        target = urlsplit(value)
        if target.scheme or target.netloc or not target.path.startswith("/") or target.path.startswith("//"):
            raise ValueError("invalid destination")
        endpoint, args = current_app.url_map.bind_to_environ(request.environ).match(target.path, method="GET")
        if args.get("vehicle_record_id") != vehicle.id or endpoint not in {
            "vehicle_karte", "vehicle_karte_history", "vehicle_karte_inspections",
            "vehicle_karte_maintenance", "vehicle_karte_maintenance_form",
            "vehicle_karte_parts", "vehicle_karte_costs", "vehicle_karte_documents", "vehicle_karte_analysis",
        }:
            raise ValueError("different vehicle page")
        base_url = url_for(endpoint, **args)
        if not target.query:
            return base_url
        query_pairs = parse_qsl(target.query, keep_blank_values=True, strict_parsing=True)
        if len({k for k, _ in query_pairs}) != len(query_pairs):
            raise ValueError("duplicate query keys")
        if any(k in {"vehicle_record_id"} for k, _ in query_pairs):
            raise ValueError("forbidden query key")
        return base_url + "?" + urlencode(query_pairs, doseq=True)
    except (ValueError, HTTPException):
        return url_for("vehicle_karte", vehicle_record_id=vehicle.id)


def add_coupling(vehicle_record_id):
    vehicle = current_vehicle(vehicle_record_id)
    require_edit_ready()
    peer = Vehicle.query.filter_by(id=request.form.get("vehicle_id", type=int),
                                   company_code=vehicle.company_code).first_or_404()
    pair = pair_kind(vehicle, peer)
    if vehicle.id == peer.id or vehicle.deleted or peer.deleted or pair is None:
        abort(400, description="有効なけん引車とトレーラーの組合せを選択してください。")
    if request.form.get("confirmed") != "yes":
        abort(400, description="車検証等で確認した組合せであることを確認してください。")
    towing, trailer, kind = pair
    link = VehicleCoupling(company_code=vehicle.company_code, towing_vehicle_id=towing.id,
                           trailer_vehicle_id=trailer.id, kind=kind,
                           created_at=datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds"),
                           created_by_username=session.get("username", ""))
    try:
        db.session.add(link)
        db.session.flush()
        add_audit_log("vehicle_coupling_add", "vehicle_coupling", str(link.id),
                      detail=f"{towing.id} → {trailer.id} ({kind})")
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409, description="この組合せは既に登録されています。画面を更新してください。")
    flash("連結車両を追加しました。", "success")
    return redirect(coupling_return_url(vehicle))


def remove_coupling(vehicle_record_id, coupling_id):
    vehicle = current_vehicle(vehicle_record_id)
    require_edit_ready()
    row = VehicleCoupling.query.filter_by(id=coupling_id, company_code=vehicle.company_code).filter(or_(
        VehicleCoupling.towing_vehicle_id == vehicle.id,
        VehicleCoupling.trailer_vehicle_id == vehicle.id,
    )).first_or_404()
    add_audit_log("vehicle_coupling_remove", "vehicle_coupling", str(row.id),
                  detail=f"{row.towing_vehicle_id} → {row.trailer_vehicle_id} ({row.kind})")
    db.session.delete(row)
    db.session.commit()
    flash("連結車両の紐づけを解除しました。", "success")
    return redirect(coupling_return_url(vehicle))


def register_vehicle_couplings(app):
    app.add_url_rule("/vehicle/karte/<int:vehicle_record_id>/couplings", "vehicle_coupling_add",
                     add_coupling, methods=["POST"])
    app.add_url_rule("/vehicle/karte/<int:vehicle_record_id>/couplings/<int:coupling_id>/remove",
                     "vehicle_coupling_remove", remove_coupling, methods=["POST"])

    @app.cli.command("init-vehicle-couplings")
    def init_vehicle_couplings():
        """Create only the vehicle-combination table on an existing database."""
        VehicleCoupling.__table__.create(db.engine, checkfirst=True)
        app.extensions["dkss"]["vehicle_couplings_schema_ready"] = True
        print("VEHICLE_COUPLINGS_INITIALIZED")
