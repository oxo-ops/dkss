"""Explicit, append-only identity reviews for saved pending driving reports."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for, make_response
from itsdangerous import BadData, URLSafeSerializer
from werkzeug.exceptions import Conflict
from sqlalchemy.exc import OperationalError

from . import access, audit, driving_access, import_owner, person_selection
from .extensions import db
from .models import Company, User, VehicleDocumentImportDraft as Draft, VehicleImportPending as Pending, VehicleImportPendingRecord as Item

KEY = 'driving_identity_reviews_v1'
BASIS = {'company_record': '原本と社内の本人資料を照合',
         'driving_record': '原本と当時の乗務記録を照合',
         'verified_material': '会社の確認済み資料と照合'}


class RecoveryConflict(Conflict):
    def __init__(self, item_id, description='本人確認または対象の状態が変わりました。最新の画面で確認してください。', code=409):
        super().__init__(description)
        self.item_id, self.code = item_id, code


def busy(error):
    sqlite_code = getattr(error.orig, 'sqlite_errorcode', None)
    return (getattr(error.orig, 'pgcode', None) in {'55P03', '40001', '40P01'}
        or isinstance(sqlite_code, int) and sqlite_code & 255 in {5, 6})


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def object_value(raw, item_id):
    try:
        value = json.loads(raw or '{}')
    except (ValueError, TypeError):
        raise RecoveryConflict(item_id, '保存済みの確認情報を読み取れません。管理者へ確認してください。') from None
    if not isinstance(value, dict):raise RecoveryConflict(item_id)
    return value


def permitted(lock=False):
    # Same company, authenticated account generation and prepared readership
    # are required in addition to the existing administrator role contract.
    if not access.require_master_admin() or not driving_access.administrator():abort(403)
    if not driving_access.ready():abort(503)
    if lock and person_selection.validate(actor_only=True) is not None:abort(409)
    identity = import_owner.identity_for_actor(session.get('company_code'), session.get('username'), lock=lock)
    actor = User.query.filter_by(company_code=session.get('company_code'), account_identity=identity).populate_existing().one_or_none() if identity else None
    if not actor or actor.role != session.get('role') or actor.password_changed_at != session.get('password_changed_at'):
        abort(403)
    return actor


def load(pending_id, item_id, lock=False):
    company = session.get('company_code')
    pending_query = Pending.query.filter_by(id=pending_id, company_code=company)
    item_query = Item.query.filter_by(id=item_id, pending_id=pending_id, company_code=company, source_kind='driving_report')
    pending = (pending_query.populate_existing().with_for_update() if lock else pending_query).first_or_404()
    item = (item_query.populate_existing().with_for_update() if lock else item_query).first_or_404()
    query = Draft.query.filter_by(id=item.document_draft_id, company_code=company, document_type='driving_report', status='completed')
    draft = (query.populate_existing().with_for_update(read=True) if lock else query).first_or_404()
    return pending, item, draft


def history(item):
    result = object_value(item.result_json, item.id)
    events = result.get(KEY, [])
    if not isinstance(events, list) or any(not isinstance(e, dict) for e in events):raise RecoveryConflict(item.id)
    return result, events


def binding(item, draft):
    payload = object_value(item.payload_json, item.id)
    preview = object_value(draft.preview_json, item.id).get('records')
    index = item.source_record_index
    if (not isinstance(preview, list) or isinstance(index, bool) or not isinstance(index, int)
        or not 0 <= index < len(preview) or preview[index] != payload
        or payload.get('vehicle_record_id') is not None
        or hashlib.sha256(draft.source_file).hexdigest() != draft.source_sha256):
        raise RecoveryConflict(item.id, '原本と保存済み明細の対応を確認できません。保留を継続してください。')
    return digest(encoded([item.company_code, item.pending_id, item.id, draft.id,
        draft.document_type, draft.status, index, draft.source_sha256,
        digest(item.payload_json), digest(encoded(preview[index]))]))


def target_state(pending, item, draft):
    return [binding(item, draft), pending.status, item.status, digest(item.result_json)]


def signer():
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt='driving-pending-identity-v1')


def event_signer():
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt='driving-pending-identity-event-v1')


def back_url(pending_id, item_id):
    return url_for('vehicle_import_pending_review', pending_id=pending_id,
        q=request.args.get('q', '')[:100], _anchor='pending-person-' + item_id)


def review_url(pending_id, item_id):
    return url_for('driving_pending_identity_review', pending_id=pending_id, item_id=item_id,
        q=request.args.get('q', '')[:100])


def navigation(pending_id):
    """All saved driving rows, independent of the ten-card display limit."""
    rows = Item.query.filter_by(company_code=session.get('company_code'), pending_id=pending_id,
        source_kind='driving_report').order_by(Item.document_draft_id, Item.source_record_index, Item.id).all()
    filenames = dict(db.session.query(Draft.id, Draft.source_filename).filter(
        Draft.company_code == session.get('company_code'), Draft.id.in_({r.document_draft_id for r in rows})).all())
    result = []
    for row in rows:
        try:
            p = object_value(row.payload_json, row.id)
            _, events = history(row)
        except RecoveryConflict:
            p, events = {}, []
            result.append({'id': row.id, 'date': row.record_date, 'index': row.source_record_index + 1,
                'draft_id': row.document_draft_id, 'filename': filenames.get(row.document_draft_id, '原本不明'),
                'url': review_url(pending_id, row.id), 'label': '確認情報を読み取れません（保留）'})
            continue
        # Do not add a new mandatory task to valid imports or intentional holds.
        choice = p.get('_driving_account_choice')
        if not events and (choice is None or isinstance(choice, str) and choice in {'', '__hold__'}):continue
        if not events and isinstance(p.get('_driving_account_identity'), str) and p['_driving_account_identity']:
            user = User.query.filter_by(company_code=row.company_code, account_identity=p['_driving_account_identity']).first()
            if user and not user.login_locked and user.role in driving_access.READER_ROLES:continue
        result.append({'id': row.id, 'date': row.record_date, 'index': row.source_record_index + 1,
            'draft_id': row.document_draft_id, 'filename': filenames.get(row.document_draft_id, '原本不明'), 'url': review_url(pending_id, row.id),
            'label': '本人確認の履歴あり（反映時に再照合）' if events and events[-1].get('decision') == 'confirmed' else '本人確認を保留'})
    return result


def render_review(pending_id, item_id, error=None, status=200):
    permitted(lock=True)
    pending, item, draft = load(pending_id, item_id)
    try:
        payload = object_value(item.payload_json, item.id)
    except RecoveryConflict as invalid:
        flash(invalid.description, 'error:')
        response = make_response(render_template('import_flow_error.html', import_flow={
            'review_url': review_url(pending_id, item_id), 'back_url': back_url(pending_id, item_id)}), 409)
        response.headers['X-DKSS-Import-Recovery'] = '1'
        response.headers['Cache-Control'] = 'private, no-store'
        return response
    try:
        _, events = history(item)
    except RecoveryConflict as invalid:
        events, error, status = [], invalid.description, 409
    editable = pending.status == 'pending' and item.status == 'pending' and error is None
    token, proof, users = '', '', []
    if editable:
        proof = person_selection.issue()  # Freeze before loading displayed choices.
        token = signer().dumps({'company': item.company_code, 'actor': session['account_identity'],
            'pending': pending.id, 'item': item.id, 'state': target_state(pending, item, draft), 'nonce': str(uuid4())})
        users = User.query.filter(User.company_code == item.company_code,
            User.role.in_(driving_access.READER_ROLES), User.login_locked.is_(False),
            User.account_identity.isnot(None)).populate_existing().order_by(User.username).all()
    recovery = dict(pending_id=pending.id, item_id=item.id, token=token, proof=proof, users=users,
        history=events, editable=editable, error=error, basis=BASIS, back_url=back_url(pending.id, item.id),
        reload_url=review_url(pending.id, item.id), navigation=navigation(pending.id),
        legacy_username=payload.get('_driving_account_choice'), legacy_uuid=payload.get('_driving_account_identity'))
    preview = object_value(draft.preview_json, item.id)
    document = dict(id=draft.id, filename=draft.source_filename, document_type='driving_report',
        record_index_offset=item.source_record_index, preview={'records': [payload], 'original_records': preview.get('original_records', [])},
        source_url=url_for('vehicle_import_pending_document_source', pending_id=pending.id, draft_id=draft.id))
    response = make_response(render_template('vehicle_document_import_preview.html', documents=[document], vehicle_choices=[],
        recovery=recovery, save_action=review_url(pending.id, item.id), edit_record=True), status)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-DKSS-Import-Recovery'] = '1'
    return response


def recovery_response(response):
    """Use the existing recovery contract before generic POST redirection."""
    if request.endpoint != 'driving_pending_identity_review':return response
    if response.status_code >= 400 and not response.get_data():
        # CSRF can fail before this view runs. Keep its denial status and offer
        # fixed GET links without reading or revealing any saved record.
        values = request.view_args or {}
        response.set_data(render_template('import_flow_error.html', import_flow={
            'review_url': review_url(values['pending_id'], values['item_id']),
            'back_url': back_url(values['pending_id'], values['item_id'])}))
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-DKSS-Import-Recovery'] = '1'
    return response


def save_review(pending_id, item_id):
    actor = permitted(lock=True)
    error = person_selection.validate(actor_only=True)
    if error is not None:raise RecoveryConflict(item_id)
    company = Company.query.filter_by(company_code=actor.company_code).populate_existing().with_for_update().first()
    if not company or company.active is not True:abort(403)
    pending, item, draft = load(pending_id, item_id, lock=True)
    result, events = history(item)
    try:
        evidence = signer().loads(request.form.get('target_token', ''))
    except BadData:
        raise RecoveryConflict(item_id) from None
    if (not isinstance(evidence, dict) or evidence.get('company') != actor.company_code
        or evidence.get('actor') != actor.account_identity or evidence.get('pending') != pending.id
        or evidence.get('item') != item.id or pending.status != 'pending' or item.status != 'pending'
        or evidence.get('state') != target_state(pending, item, draft) or not evidence.get('nonce')
        or any(e.get('id') == evidence['nonce'] for e in events)):
        raise RecoveryConflict(item.id)
    decision = request.form.get('decision')
    reference = request.form.get('evidence_reference', '').strip()
    if decision not in {'confirmed', 'hold'} or len(reference) > 1000:abort(400)
    user, basis = None, 'hold'
    if decision == 'confirmed':
        username = request.form.get('reader_username', '').strip()
        basis = request.form.get('evidence_basis')
        if not username or basis not in BASIS or request.form.get('checked') != 'yes':abort(400)
        error = person_selection.validate(selected_usernames=[username])
        if error is not None:raise RecoveryConflict(item.id)
        user = User.query.filter(User.company_code == actor.company_code, User.username == username,
            User.role.in_(driving_access.READER_ROLES), User.login_locked.is_(False),
            User.account_identity.isnot(None)).populate_existing().with_for_update(read=True).one_or_none()
        if not user:raise RecoveryConflict(item.id)
    event = dict(id=evidence['nonce'], decision=decision, company=item.company_code, pending_id=pending.id,
        item_id=item.id, draft_id=draft.id, source_record_index=item.source_record_index,
        source_sha256=draft.source_sha256, source_binding=binding(item, draft), target_version=digest(encoded(evidence['state'])),
        account_identity=user.account_identity if user else None, username=user.username if user else None,
        person_name=((user.last_name or '') + (user.first_name or '')) if user else None,
        actor_identity=actor.account_identity, actor_username=actor.username,
        actor_name=(actor.last_name or '') + (actor.first_name or ''), at=datetime.now(timezone.utc).isoformat(),
        evidence_basis=basis, evidence_reference=reference, previous=events[-1].get('id') if events else None,
        legacy_selection={k: object_value(item.payload_json, item.id).get(k) for k in
            ('_driving_account_choice', '_driving_account_identity')})
    event['proof'] = event_signer().dumps(event)
    item.result_json = encoded({**result, KEY: [*events, event]})
    detail = encoded({k: event[k] for k in ('id', 'decision', 'item_id', 'source_binding', 'account_identity', 'evidence_basis', 'evidence_reference')})
    audit.add_audit_log('driving_pending_identity_review', target_type='vehicle_import_pending_record',
        target_id=item.id, detail=detail)
    db.session.commit()
    flash('本人確認を記録しました。登録待ちから反映できます。' if user else '本人確認を保留しました。登録・公開はしていません。', 'success')
    return redirect(back_url(pending.id, item.id))


def driving_pending_identity_review(pending_id, item_id):
    try:
        return save_review(pending_id, item_id) if request.method == 'POST' else render_review(pending_id, item_id)
    except RecoveryConflict as error:
        db.session.rollback()
        return render_review(pending_id, item_id, error.description, error.code)
    except OperationalError as error:
        db.session.rollback()
        if busy(error):return render_review(pending_id, item_id, '別の確認・反映処理が実行中です。最新の状態で確認し直してください。', 409)
        raise
    except Exception:
        db.session.rollback()
        raise


def effective_selection(item, draft):
    """Return a trusted override without changing the saved payload or preview."""
    _, events = history(item)
    if not events:return None
    permitted()
    latest = events[-1]
    try:
        signed = event_signer().loads(latest.get('proof', ''))
    except BadData:
        raise RecoveryConflict(item.id) from None
    if signed != {key: value for key, value in latest.items() if key != 'proof'}:raise RecoveryConflict(item.id)
    if (latest.get('decision') != 'confirmed' or latest.get('source_binding') != binding(item, draft)
        or latest.get('company') != item.company_code or latest.get('item_id') != item.id
        or latest.get('pending_id') != item.pending_id or latest.get('draft_id') != draft.id
        or not latest.get('actor_identity') or not latest.get('account_identity')):
        raise RecoveryConflict(item.id)
    user = User.query.filter_by(company_code=item.company_code, account_identity=latest['account_identity']).populate_existing().with_for_update(read=True).one_or_none()
    if not user or user.login_locked or user.role not in driving_access.READER_ROLES:raise RecoveryConflict(item.id)
    return user.username, user.account_identity, {'event_id': latest['id'], 'pending_id': item.pending_id,
        'item_id': item.id, 'confirmed_by': latest['actor_identity'], 'confirmed_at': latest['at']}
