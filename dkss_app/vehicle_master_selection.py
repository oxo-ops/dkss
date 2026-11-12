"""Bind vehicle form choices to the master generations actually displayed.

Names remain the form/storage values. One signed catalogue avoids JavaScript
dependencies and per-option signatures; confirmations/cookie recovery retain
only the selected entries. This is not a vehicle concurrent-edit version.
"""
from flask import current_app, flash, session
from itsdangerous import BadData, URLSafeSerializer

from .account_identity import current_identity
from .master_generations import valid_generation


FIELD = 'vehicle_master_selection'
MESSAGE = '営業所・車種の選択情報が古いか不正です。画面を再読み込みして選び直してください。'
KINDS = {'type': 'vehicle-types', 'office': 'offices'}


def _serializer():
    return URLSafeSerializer(current_app.secret_key, salt='q04-vehicle-selection-v1')


def _context(vehicle_id):
    return [session.get('company_code'), current_identity(), vehicle_id]


def _load(form_data, vehicle_id):
    token = form_data.get(FIELD)
    if not valid_generation(current_identity()) or not isinstance(token, str) or not token:
        return None
    try:
        payload = _serializer().loads(token)
    except BadData:
        return None
    if not isinstance(payload, dict) or payload.get('context') != _context(vehicle_id):
        return None
    for key in KINDS:
        entries = payload.get(key)
        if not isinstance(entries, list) or any(
            not isinstance(entry, list) or len(entry) != 3
            or not isinstance(entry[0], str)
            or type(entry[1]) is not int or entry[1] <= 0
            or not valid_generation(entry[2])
            for entry in entries
        ):
            return None
    return payload


def compact_form_data(form_data, vehicle_id=None):
    """Never copy an entire catalogue into the session cookie or confirmation."""
    values = dict(form_data)
    payload = _load(values, vehicle_id)
    values[FIELD] = ''
    if payload is not None:
        selections = {}
        for key in KINDS:
            name = (values.get(key) or '').strip()
            selections[key] = [entry for entry in payload.get(key, []) if entry[0] == name]
        values[FIELD] = _serializer().dumps(dict(context=payload['context'], **selections))
    return values


def validate(form_data, vehicle_id=None):
    from .models import Office, VehicleType

    payload = _load(form_data, vehicle_id)
    if payload is None:
        return [(MESSAGE, 'office'), (MESSAGE, 'type')]
    errors = []
    for key, model in (('type', VehicleType), ('office', Office)):
        name = (form_data.get(key) or '').strip()
        if not name:
            continue
        entries = [entry for entry in payload.get(key, []) if entry[0] == name]
        row = None
        if len(entries) == 1:
            _, ident, generation = entries[0]
            if valid_generation(generation):
                # The predicate and lock are one query, in the saving transaction.
                # FOR SHARE prevents rename/delete until the vehicle commit.
                row = model.query.filter_by(
                    company_code=session.get('company_code'), id=ident,
                    master_generation=generation, name=name,
                ).with_for_update(read=True).first()
        if row is None:
            errors.append((MESSAGE, key))
    return errors


def form_context(vehicle=None, vehicle_id=None, restored=False):
    from .master_readers import offices_for_current_company
    from .vehicle_readers import vehicle_types_for_current_company

    values = dict(vehicle or {})
    if restored and vehicle:
        errors = validate(values, vehicle_id)
        for _, key in errors:
            values[key] = ''
        if errors:
            flash(MESSAGE, 'error:office')
    offices = offices_for_current_company(include_generation=True)
    types = vehicle_types_for_current_company(include_generation=True)
    payload = {'context': _context(vehicle_id)}
    for key, choices in (('office', offices), ('type', types)):
        payload[key] = [[row['name'], row['id'], row['master_generation']]
                        for row in choices if valid_generation(row['master_generation'])]
        if values.get(key) and not any(entry[0] == values[key] for entry in payload[key]):
            # An unknown stored name must not select the first current master.
            values[key] = ''
            flash(MESSAGE, 'error:' + key)
    return {'vehicle': values, 'offices': offices, 'vehicle_types': types,
            FIELD: _serializer().dumps(payload) if valid_generation(current_identity()) else ''}
