"""Shared recovery and company-scoped duplicate guidance for vehicle imports."""
import hashlib
from . import import_owner as _dkss_import_owner
from flask import request, session, url_for, jsonify, render_template, redirect, flash, abort
from sqlalchemy.orm import defer
from .extensions import db
from . import access, serialization
from .models import VehicleDocumentImportDraft as DocumentDraft, VehicleOperationImportDraft as OperationDraft

DOCUMENT = {'vehicle_data_import', 'vehicle_data_import_progress', 'enqueue_documents',
    'vehicle_document_import_preview', 'vehicle_document_import_confirm', 'document_import_job',
    'document_import_status', 'retry_document_import', 'delete_document_import', 'document_import_kind'}
OPERATION = {'vehicle_operation_import', 'vehicle_operation_import_preview',
    'vehicle_operation_import_confirm', 'vehicle_operation_import_add_vehicle', 'vehicle_operation_import_result'}
REGISTRATION = {'vehicle_registration_method', 'import_vehicles', 'confirm_vehicle_import',
    'extract_vehicle_certificate_route', 'vehicle_certificate_register', 'new_vehicle', 'vehicle_excel_import_preview'}


def context():
    endpoint = request.endpoint
    if endpoint == 'cancel_import_flow':
        endpoint = {'document': 'vehicle_document_import_preview', 'operation': 'vehicle_operation_import_preview',
            'registration': 'confirm_vehicle_import'}.get(request.args.get('kind'))
    if endpoint in DOCUMENT:
        kind, origin = 'document', 'vehicle_data_import'
    elif endpoint in OPERATION:
        kind, origin = 'operation', 'vehicle_data_import'
    elif endpoint in REGISTRATION:
        kind, origin = 'registration', 'vehicle_registration_method'
    else:
        return None
    key = (request.args.get('key', '') if request.endpoint == 'cancel_import_flow' else
        (request.view_args or {}).get('batch_id' if kind == 'document' else 'draft_id', ''))
    if kind == 'registration' and request.endpoint == 'confirm_vehicle_import':
        key = request.form.get('vehicle_excel_import_draft', '')
    review_url = (url_for('vehicle_document_import_preview', batch_id=key) if kind == 'document' and key else
        url_for('vehicle_operation_import_preview', draft_id=key) if kind == 'operation' and key else
        url_for('vehicle_excel_import_preview', draft_id=key) if kind == 'registration' and key else None)
    if endpoint == 'document_import_kind':
        review_url = url_for('document_import_kind', draft_id=request.view_args['draft_id'])
    entry = request.method == 'GET' and request.endpoint in {'vehicle_data_import', 'vehicle_registration_method', 'vehicle_operation_import', 'import_vehicles'} and request.args.get('complete') != '1'
    return {'kind': kind, 'key': key, 'entry': entry, 'review_url': review_url, 'back_url': url_for(origin),
        'cancel_url': url_for('cancel_import_flow', kind=kind, key=key),
        'show_cancel': bool(key or endpoint in {'confirm_vehicle_import', 'new_vehicle'} or
            (endpoint == 'import_vehicles' and request.method == 'POST'))}


def normalize_errors(errors):
    return [{'message': str(item[0]) if isinstance(item, (tuple, list)) else str(item),
             'field': (item[1] or '') if isinstance(item, (tuple, list)) and len(item) == 2 else ''}
            for item in errors]


def wants_json():
    return (request.headers.get('X-DKSS-Validation-Only') == '1' or
        request.headers.get('X-DKSS-Final-Submit') == '1' or
        request.accept_mimetypes.best == 'application/json')


def form_error_response(errors, status_code):
    flow = context()
    if not flow:
        return None
    errors = normalize_errors(errors)
    if wants_json():
        response = jsonify(errors=errors)
    else:
        response = render_template('import_flow_error.html', import_flow=flow, import_flow_errors=errors)
        from flask import make_response
        response = make_response(response)
    response.status_code = status_code
    response.headers['X-DKSS-Form-Errors'] = '1'
    response.headers['X-DKSS-Import-Recovery'] = '1'
    response.headers['X-DKSS-Form-Error-Count'] = str(len(errors))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def completed_document(company_code, document_type, source_digest):
    """A fully imported source is shared within its company, regardless of creator."""
    rows = DocumentDraft.query.options(defer(DocumentDraft.source_file)).filter_by(
        company_code=company_code, document_type=document_type,
        source_sha256=source_digest, status='completed').all()
    for row in rows:
        preview = serialization.safe_json_dict(row.preview_json)
        result = serialization.safe_json_dict(row.result_json)
        records = preview.get('records')
        imported = result.get('records', []) + result.get('pending_records', [])
        if isinstance(records, list) and records and len(imported) >= len(records):
            return True
    return False


def mark_document_duplicates(drafts, documents, company_code):
    from .vehicle_imports import registered_maintenance_import_keys, maintenance_import_source_keys, registered_inspection_import_keys
    maintenance = registered_maintenance_import_keys(company_code) if any(row.document_type == 'maintenance' for row in drafts) else set()
    keys = {kind: registered_inspection_import_keys(company_code, source_kind=kind)
        for kind in ('inspection', 'driving_report') if any(row.document_type == kind for row in drafts)}
    seen_maintenance = set()
    duplicates = total = 0
    for row, document in zip(drafts, documents):
        for index, record in enumerate(document['preview'].get('records') or []):
            total += 1
            if row.document_type == 'maintenance':
                source = maintenance_import_source_keys({'sha256': row.source_sha256,
                    'pages': record.get('source_pages'), 'record_index': index})
                duplicate = bool(source & (maintenance | seen_maintenance))
                seen_maintenance.update(source)
            else:
                key = (row.source_sha256, index)
                duplicate = key in keys.get(row.document_type, set())
                keys.setdefault(row.document_type, set()).add(key)
            if duplicate:
                record['include'] = False
                record['import_duplicate'] = True
                duplicates += 1
    if not duplicates:
        return None
    return ('すべての記録が同じ会社ですでに登録済みです。キャンセルして元の画面へ戻れます。'
        if duplicates == total else
        f'{duplicates}件は同じ会社で登録済みのため、取り込み対象から外しました。未登録の記録だけ続けられます。')


def cancel_import_flow():
    if not access.require_master_admin():
        abort(403)
    kind = request.args.get('kind')
    key = request.args.get('key', '')
    if kind not in {'document', 'operation', 'registration'}:
        abort(400)
    if key and kind == 'document':
        from .document_import_queue import delete_receipt
        if not delete_receipt(key, session.get('company_code'), session.get('username')):
            abort(404)
    elif key and kind == 'registration':
        row = DocumentDraft.query.filter_by(batch_id=key, document_type='vehicle_excel', company_code=session.get('company_code')).filter(_dkss_import_owner.owner_clause(DocumentDraft)).with_for_update().first_or_404()
        if row.status == 'preview':
            row.status = 'deleted'
            row.source_file = b''
            db.session.commit()
    elif key and kind == 'operation':
        row = OperationDraft.query.filter_by(id=key, company_code=session.get('company_code'),
            created_by_username=session.get('username')).with_for_update().first_or_404()
        if row.status == 'preview':
            row.status = 'cancelled'
            row.source_file = b''
            row.selection_json = '{}'
            db.session.commit()
    # Excel/certificate candidates live in the browser: leaving discards only that review.
    flash('取り込みをキャンセルしました。登録済みのデータは変更していません。' if key or kind == 'registration' else
        '元の画面に戻りました。送信が受け付けられていた場合は、受付済みの資料から状況を確認できます。', 'info')
    return redirect(url_for('vehicle_registration_method' if kind == 'registration' else 'vehicle_data_import'), code=303)


def store_excel_review(upload, company_code, username):
    from uuid import uuid4
    upload.stream.seek(0)
    source = upload.stream.read()
    key = str(uuid4())
    row = DocumentDraft(id=key, batch_id=key, company_code=company_code,
        created_by_username=username, document_type='vehicle_excel', source_filename=upload.filename,
        source_file=source, source_sha256=hashlib.sha256(source).hexdigest(),
        status='preview', preview_json='{}', result_json='{}')
    db.session.add(row)
    db.session.commit()
    return row


def vehicle_excel_import_preview(draft_id):
    if not access.require_master_admin():
        abort(403)
    row = DocumentDraft.query.filter_by(id=draft_id, document_type='vehicle_excel', company_code=session.get('company_code')).filter(_dkss_import_owner.owner_clause(DocumentDraft)).first_or_404()
    if row.status != 'preview':
        flash('このExcelの確認は終了しています。登録結果を確認してください。', 'info')
        return redirect(url_for('vehicle_registration_method'))
    from io import BytesIO
    from werkzeug.datastructures import FileStorage
    from .vehicle_master import import_vehicles
    return import_vehicles(FileStorage(stream=BytesIO(row.source_file), filename=row.source_filename), row.id)


def register_import_flow(app):
    app.add_url_rule('/master/vehicles/import/review/<draft_id>', 'vehicle_excel_import_preview', vehicle_excel_import_preview)
    app.add_url_rule('/vehicle/import-flow/cancel', 'cancel_import_flow', cancel_import_flow, methods=['POST'])

    @app.context_processor
    def import_flow_context():
        return {'import_flow': context()}

    @app.after_request
    def recover_import_error(response):
        if not context() or response.status_code < 400 or response.headers.get('X-DKSS-Form-Errors') == '1':
            return response
        if response.is_json:
            data = response.get_json(silent=True) or {}
            if data.get('errors') or data.get('error'):
                return response
        messages = {400: '送信内容を確認できませんでした。内容を修正するか、キャンセルして元の画面へ戻ってください。',
            403: 'この操作の権限またはログイン状態を確認してください。',
            404: '確認中の資料が見つかりません。取り込み済み・取消済みの可能性があります。',
            413: 'ファイル容量が上限を超えています。ファイルを分けるか、選び直してください。',
            429: '操作が集中しています。少し待ってから再試行してください。'}
        recovered = form_error_response([(messages.get(response.status_code,
            '処理を完了できませんでした。入力内容はこの画面で確認できます。登録結果を確認してから再試行してください。'), '')], response.status_code)
        if response.headers.get('Retry-After'):
            recovered.headers['Retry-After'] = response.headers['Retry-After']
        return recovered
