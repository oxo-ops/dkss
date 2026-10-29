"""Master Readers responsibilities; routes are registered by the application factory."""
from . import access as _dkss_access, audit as _dkss_audit, common as _dkss_common, models as _dkss_models


def get_company(company_code):
    return _dkss_models.Company.query.filter_by(
        company_code=company_code
    ).first()


def office_reference_is_current(company_code, name):
    """Protect a nonempty office copied from a related row until history commits."""
    if not name:
        return True
    return _dkss_models.Office.query.filter_by(
        company_code=company_code, name=name
    ).with_for_update(read=True).first() is not None



def ordered_master_query(model, company_code, query=None):
    """Apply saved order before limiting candidates; new IDs follow saved IDs."""
    kinds = {_dkss_models.Office: "offices", _dkss_models.VehicleType: "vehicle-types",
             _dkss_models.LicenseType: "license-types", _dkss_models.DeliveryPlace: "delivery-places",
             _dkss_models.Checklist: "checklists", _dkss_models.PatrolContentType: "patrol-content-types", _dkss_models.Manual: "manuals"}
    query = model.query if query is None else query
    query = query.filter(model.company_code == company_code).order_by(None)
    saved = _dkss_models.MasterDisplayOrder.query.filter_by(
        company_code=company_code, kind=kinds[model]
    ).first()
    ids = _dkss_common.json.loads(saved.ordered_ids_json) if saved else []
    if ids:
        rank = _dkss_common.case({item_id: i for i, item_id in enumerate(ids)},
                    value=model.id, else_=len(ids))
        query = query.order_by(rank)
    return query.order_by(model.id.asc())



def save_master_display_order(kind):
    if not _dkss_access.require_master_admin():
        return {"ok": False, "message": "管理者のみ変更できます。"}, 403
    models = {"offices": _dkss_models.Office, "vehicle-types": _dkss_models.VehicleType,
              "license-types": _dkss_models.LicenseType, "delivery-places": _dkss_models.DeliveryPlace,
              "checklists": _dkss_models.Checklist, "patrol-content-types": _dkss_models.PatrolContentType, "manuals": _dkss_models.Manual}
    model = models.get(kind)
    if model is None:
        return {"ok": False, "message": "対象のマスタがありません。"}, 404
    data = _dkss_common.request.get_json(silent=True)
    if not isinstance(data, dict):
        return {"ok": False, "message": "並び順の形式が不正です。"}, 400
    ids, previous_ids = data.get("ids"), data.get("previous_ids")
    if any(not isinstance(values, list)
           or any(type(value) is not int or value <= 0 for value in values)
           or len(values) != len(set(values))
           for values in (ids, previous_ids)):
        return {"ok": False, "message": "並び順の形式が不正です。"}, 400
    company_code = _dkss_common.session.get("company_code")
    saved = _dkss_models.MasterDisplayOrder.query.filter_by(
        company_code=company_code, kind=kind
    ).first()
    current_ids = [item.id for item in ordered_master_query(model, company_code).all()]
    if previous_ids != current_ids or set(ids) != set(current_ids):
        return {"ok": False, "message": "一覧が更新されています。再読み込みして並べ替えてください。"}, 409
    if ids == current_ids:
        return _dkss_common.jsonify(ok=True, ids=ids)
    if saved is None:
        saved = _dkss_models.MasterDisplayOrder(company_code=company_code, kind=kind)
        _dkss_common.db.session.add(saved)
    saved.ordered_ids_json = _dkss_common.json.dumps(ids)
    _dkss_audit.add_audit_log(action="master_order_changed", target_type=kind,
                  detail="表示順変更: " + _dkss_common.json.dumps(ids), company_code=company_code)
    try:
        _dkss_common.db.session.commit()
    except _dkss_common.SQLAlchemyError:
        _dkss_common.db.session.rollback()
        return {"ok": False, "message": "保存できませんでした。再読み込みして再度お試しください。"}, 409
    return _dkss_common.jsonify(ok=True, ids=ids)



def remove_master_from_display_order(kind, item):
    # SQLite may reuse a deleted highest ID. Remove it before later registrations.
    saved = _dkss_models.MasterDisplayOrder.query.filter_by(
        company_code=item.company_code, kind=kind
    ).first()
    if saved:
        saved.ordered_ids_json = _dkss_common.json.dumps([
            ident for ident in _dkss_common.json.loads(saved.ordered_ids_json) if ident != item.id
        ])



def inject_master_office_order():
    # The planning page builds its office selector asynchronously in JavaScript.
    if _dkss_common.request.endpoint != "vehicle_inspection_plans" or not _dkss_common.session.get("company_code"):
        return {}
    return {"master_office_order": [item.name for item in ordered_master_query(
        _dkss_models.Office, _dkss_common.session["company_code"]
    ).all()]}



def offices_for_current_company():
    query = ordered_master_query(_dkss_models.Office, _dkss_common.session.get("company_code"))

    return [
        {
            "id": office.id,
            "master_generation": office.master_generation,
            "index": office.id,
            "company_code": office.company_code,
            "name": office.name
        }
        for office in query.all()
    ]



def delivery_places_for_current_company():
    query = ordered_master_query(_dkss_models.DeliveryPlace, _dkss_common.session.get("company_code"))

    return [
        {
            "id": place.id,
            "master_generation": place.master_generation,
            "index": place.id,
            "company_code": place.company_code,
            "name": place.name
        }
        for place in query.all()
    ]



def patrol_content_types_for_current_company():
    query = ordered_master_query(_dkss_models.PatrolContentType, _dkss_common.session.get("company_code"))

    return [
        {
            "id": item.id,
            "master_generation": item.master_generation,
            "index": item.id,
            "company_code": item.company_code,
            "name": item.name
        }
        for item in query.all()
    ]



def manuals_for_current_company():
    query = ordered_master_query(_dkss_models.Manual, _dkss_common.session.get("company_code"))

    return [
        {
            "id": manual.id,
            "index": manual.id,
            "company_code": manual.company_code,
            "title": manual.title,
            "category": manual.category,
            "filename": manual.filename,
        }
        for manual in query.all()
    ]
