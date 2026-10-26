"""Short HTTP requests for durable document intake and status polling."""
from collections import OrderedDict
from flask import current_app, request, session, jsonify, redirect, url_for, render_template, flash
from werkzeug.exceptions import NotFound
from . import access, http
from .models import VehicleDocumentImportDraft as Draft
from . import document_import_queue as queue
from .document_import_worker import start_worker


def own_batch(batch_id):
    if not access.require_master_admin():
        raise NotFound()
    status = queue.batch_status(batch_id, session.get('company_code'), session.get('username'))
    if not status:
        raise NotFound()
    status['status_url'] = url_for('document_import_status', batch_id=batch_id)
    status['page_url'] = url_for('document_import_job', batch_id=batch_id)
    status['preview_url'] = url_for('vehicle_document_import_preview', batch_id=batch_id) if status['preview_ready'] else None
    return status


def queue_error(errors, status_code=400):
    if request.accept_mimetypes.best == 'application/json':
        return jsonify(errors=[{'message':message, 'field':field} for message,field in errors]), status_code
    return http.return_form_errors(errors, status_code=status_code)


def enqueue_documents():
    if not access.require_master_admin() or not session.get('company_code') or not session.get('username'):
        return queue_error([('ログイン情報と権限を確認してください。','')], status_code=403)
    # Apply the bound before multipart parsing; leave unrelated uploads unchanged.
    request.max_content_length = queue.MAX_BATCH_BYTES + queue.MB
    if request.content_length and request.content_length > request.max_content_length:
        return queue_error([('1回の合計容量は200MB以下にしてください。','document_files')], status_code=413)
    try:
        batch_id = queue.enqueue(request.files.getlist('document_files'), request.form.get('document_type'),
            session['company_code'], session['username'], request.form.get('upload_key'))
    except queue.ImportQueueError as error:
        return queue_error([(str(error),'document_files')], status_code=error.status)
    status = own_batch(batch_id)
    start_worker(current_app._get_current_object())
    if request.accept_mimetypes.best == 'application/json':
        return jsonify(status), 202
    return redirect(status['page_url'], code=303)


def document_import_status(batch_id):
    status = own_batch(batch_id)
    if not status['finished']:
        start_worker(current_app._get_current_object())
    response = jsonify(status)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def document_import_job(batch_id):
    status = own_batch(batch_id)
    if not status['finished']:
        start_worker(current_app._get_current_object())
    return render_template('document_import_job.html', job=status)


def retry_document_import(batch_id):
    own_batch(batch_id)
    queue.retry_failed(batch_id, session.get('company_code'), session.get('username'))
    start_worker(current_app._get_current_object())
    return redirect(url_for('document_import_job', batch_id=batch_id), code=303)


def delete_document_import(batch_id):
    own_batch(batch_id)
    if not queue.delete_receipt(batch_id, session.get('company_code'), session.get('username')):
        raise NotFound()
    flash('受付を削除しました。登録済みの車両記録と原本は保持しています。', 'success')
    return redirect(url_for('vehicle_data_import'), code=303)


def recent_imports():
    if not access.require_master_admin():
        return []
    rows = queue.lightweight_query().filter_by(company_code=session.get('company_code'),
        created_by_username=session.get('username')).filter(Draft.status.in_((*queue.ACTIVE, 'preview', 'read_error'))).order_by(Draft.created_at.desc()).limit(100).all()
    batches = OrderedDict()
    for row in rows:
        if row.document_type not in {'maintenance', 'inspection', 'driving_report'} or row.status not in {*queue.ACTIVE, 'preview', 'read_error'}:
            continue
        if row.status == 'deleted' or queue.receipt_hidden(row.result_json):
            continue
        if queue.metadata(row.result_json) or row.status in (*queue.ACTIVE, 'preview', 'completed', 'skipped'):
            batches.setdefault(row.batch_id, []).append(row)
    result = []
    for batch_id, files in list(batches.items())[:12]:
        statuses = {row.status for row in files}
        if statuses.intersection(queue.ACTIVE):
            state, label = 'reading', '読み取り中'
        elif 'read_error' in statuses:
            state, label = 'error', '読み取り失敗'
        elif 'preview' in statuses:
            state, label = 'ready', '確認できます'
        else:
            state, label = 'completed', '登録済み' if 'completed' in statuses else '確認済み'
        result.append({'batch_id': batch_id, 'filename': files[0].source_filename,
            'count': len(files), 'state': state, 'label': label,
            'url': url_for('document_import_job', batch_id=batch_id)})
    return result
