"""Durable OCR jobs using existing draft rows; ownership is fenced by a lease token.

Only queued/reading/read_error statuses use result_json['ocr_job']. Confirmed import
results retain their existing schema. No schema migration or new service is required.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from uuid import uuid4, uuid5, UUID
from sqlalchemy.orm import load_only
from sqlalchemy.exc import IntegrityError
from .extensions import db
from .models import VehicleDocumentImportDraft as Draft, Company, User
from document_type_detection import detect_document_types, validate_detection
from .document_sources import store_source

MB = 1024 * 1024
MAX_FILE_BYTES = 20 * MB
MAX_BATCH_FILES = 50
MAX_BATCH_BYTES = 200 * MB
LEASE_SECONDS = 120
MAX_ATTEMPTS = 3
ACTIVE = ('queued', 'reading')


def now():
    return datetime.now(timezone.utc)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def metadata(value):
    try:
        data = json.loads(value or '{}')
        job = data.get('ocr_job') if isinstance(data, dict) else None
        return job if isinstance(job, dict) else {}
    except (TypeError, ValueError):
        return {}


def result(job):
    return encode({'ocr_job': job})


def receipt_hidden(value):
    try:
        data = json.loads(value or '{}')
        return isinstance(data, dict) and data.get('receipt_hidden') is True
    except (TypeError, ValueError):
        return False


def delete_receipt(batch_id, company_code, username):
    """Cancel unfinished intake; retain originals used by registered records."""
    rows = lightweight_query().filter_by(batch_id=batch_id, company_code=company_code,
        created_by_username=username).order_by(Draft.id).with_for_update().all()
    if not rows or all(receipt_hidden(row.result_json) for row in rows):
        db.session.rollback()
        return False
    for row in rows:
        data = json.loads(row.result_json or '{}')
        data['receipt_hidden'] = True
        if row.status in (*ACTIVE, 'processing', 'preview', 'read_error', 'type_review'):
            # Tombstones fence running workers and keep the upload key idempotent.
            row.status = 'deleted'
            row.source_file = b''
            row.preview_json = '{}'
            data = {'receipt_hidden': True, 'deleted': True, 'at': now().isoformat()}
        row.result_json = encode(data)
    from .document_sources import purge_unreferenced
    for company, digest in sorted({(r.company_code, r.source_sha256) for r in rows}):
        purge_unreferenced(company, digest)
    db.session.commit()
    return True


def lightweight_query():
    return Draft.query.options(load_only(Draft.id, Draft.batch_id, Draft.company_code,
        Draft.created_by_username, Draft.document_type, Draft.source_filename,
        Draft.source_sha256, Draft.status, Draft.result_json, Draft.created_at))


class ImportQueueError(ValueError):
    def __init__(self, message, status=400):
        self.status = status
        super().__init__(message)


def enqueue(files, document_type, company_code, username, upload_key=None):
    """Store each source without retaining the whole batch in Python memory."""
    from .storage import is_valid_uploaded_file
    if document_type not in {'maintenance', 'inspection', 'driving_report'}:
        raise ImportQueueError('請求書・点検記録・安全運転日報を選択してください。')
    try:
        batch_id = str(UUID(upload_key)) if upload_key else str(uuid4())
    except (ValueError, TypeError, AttributeError):
        raise ImportQueueError('受付番号を確認してください。') from None
    existing = lightweight_query().filter_by(batch_id=batch_id, company_code=company_code,
                                             created_by_username=username).first()
    if existing:
        return batch_id
    files = [file for file in files if file and file.filename]
    if not 1 <= len(files) <= MAX_BATCH_FILES:
        raise ImportQueueError('資料を1～50ファイル選択してください。')
    pending = Draft.query.filter_by(company_code=company_code, created_by_username=username).filter(Draft.status.in_(ACTIVE)).count()
    if pending + len(files) > 100:
        raise ImportQueueError('受付済みの資料を処理中です。完了後に追加してください。', 409)
    total = 0
    accepted = 0
    ignored = []
    from .import_flow import completed_document
    try:
        for position, file in enumerate(files):
            filename = os.path.basename(file.filename.replace('\\', '/'))
            extension = os.path.splitext(filename)[1].lower()
            if not filename or len(filename) > 255 or extension not in {'.pdf','.png','.jpg','.jpeg'}:
                raise ImportQueueError('PDF・PNG・JPEGを選択し、ファイル名を255文字以内にしてください。')
            if not is_valid_uploaded_file(file, extension):
                raise ImportQueueError(filename + '：ファイルの内容が不正です。')
            file.stream.seek(0)
            source = file.stream.read(MAX_FILE_BYTES + 1)
            if not source or len(source) > MAX_FILE_BYTES:
                raise ImportQueueError(filename + '：空の資料、または20MBを超える資料は取り込めません。')
            total += len(source)
            if total > MAX_BATCH_BYTES:
                raise ImportQueueError('1回の合計容量は200MB以下にしてください。', 413)
            digest = hashlib.sha256(source).hexdigest()
            if completed_document(company_code, document_type, digest):
                ignored.append(filename)
                del source
                continue
            accepted += 1
            row = Draft(id=str(uuid5(UUID(batch_id), company_code + ':' + username + ':' + str(position))), batch_id=batch_id, company_code=company_code,
                created_by_username=username, document_type=document_type, source_filename=filename,
                source_file=store_source(company_code,digest,source), source_sha256=digest, status='queued',
                preview_json='{}', result_json=result({'phase':'queued', 'attempts':0,
                'position':position, 'requested_type':document_type, 'generation':0,
                'updated_at':now().isoformat(), 'bytes':len(source)}))
            db.session.add(row)
            db.session.flush()
            db.session.expunge(row)
            del row, source
        if not accepted:
            raise ImportQueueError('選択した資料は、同じ会社ですでに登録済みです。他の利用者による登録も含みます。同じ資料の再登録は不要です。', 409)
        if ignored:
            first = lightweight_query().filter_by(batch_id=batch_id, company_code=company_code,
                created_by_username=username).first()
            data = metadata(first.result_json)
            data['ignored_files'] = ignored
            first.result_json = result(data)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if lightweight_query().filter_by(batch_id=batch_id, company_code=company_code,
                                          created_by_username=username).first():
            return batch_id
        raise
    except Exception:
        db.session.rollback()
        raise
    return batch_id


def claim_next():
    from .document_schedule import claim_fair, ready as schedule_ready
    return claim_fair() if schedule_ready() else claim_legacy()


def claim_legacy():
    """Compare-and-swap ownership, compatible with both SQLite and PostgreSQL."""
    rows = lightweight_query().filter(Draft.status.in_(ACTIVE)).order_by(Draft.created_at, Draft.id).limit(200).all()
    for row in rows:
        original = row.result_json
        job = metadata(original)
        if not job:
            continue
        if row.status == 'reading' and str(job.get('lease_until','')) > now().isoformat():
            continue
        attempts = job.get('attempts', 0)
        job.update(attempts=attempts + 1, updated_at=now().isoformat())
        if attempts >= MAX_ATTEMPTS:
            status = 'read_error'
            job.update(phase='error', message='処理が繰り返し中断しました。「失敗分を再実行」からやり直してください。')
        else:
            status = 'reading'
            job.update(phase='reading', token=str(uuid4()), lease_until=(now()+timedelta(seconds=LEASE_SECONDS)).isoformat())
        key = row.id
        changed = Draft.query.filter_by(id=key, status=row.status, result_json=original).update(
            {'status':status, 'result_json':result(job)}, synchronize_session=False)
        db.session.commit()
        if changed and status == 'reading':
            return key, job['token']
    return None


def renew(draft_id, token, update=None):
    row = lightweight_query().filter_by(id=draft_id, status='reading').first()
    if not row:
        db.session.rollback()
        return False
    original = row.result_json
    job = metadata(original)
    if job.get('token') != token:
        db.session.rollback()
        return False
    if update:
        if update.get('phase') in {'classifying','reading','ai_accepted','ai_output','checking'}:
            job['phase'] = update['phase']
        count = update.get('received_lines')
        if type(count) is int and 0 <= count <= 100000:
            job['received_lines'] = count
    job.update(lease_until=(now()+timedelta(seconds=LEASE_SECONDS)).isoformat(), updated_at=now().isoformat())
    changed = Draft.query.filter_by(id=draft_id, status='reading', result_json=original).update(
        {'result_json':result(job)}, synchronize_session=False)
    db.session.commit()
    return bool(changed)


def failure_message(error):
    code = str(error).split(':',1)[0]
    mapping = {
        'API_KEY_NOT_SET':'AIの接続設定を確認してください。',
        'OPENAI_NETWORK_OR_TIMEOUT':'AIとの通信が時間切れになりました。失敗した資料だけ再実行できます。',
        'EXTRACTION_NOT_COMPLETED':'AIの読み取りが完了しませんでした。',
        'NO_INVOICE_FOUND':'整備請求書を確認できませんでした。',
        'NO_INSPECTION_FOUND':'点検記録を確認できませんでした。',
        'NO_DRIVING_REPORT_FOUND':'安全運転日報を確認できませんでした。',
        'OCR_NO_RECORDS':'資料の内容を読み取れませんでした。',
        'SOURCE_CHANGED':'保存済みの原本を確認できませんでした。',
        'OWNER_UNAVAILABLE':'受付した利用者の権限または会社の利用状態を確認してください。',
    }
    # Raw API messages may contain credentials or sensitive source text.
    return mapping.get(code, '読み取りに失敗しました。原本を確認して再実行してください。')


def finish(draft_id, token, extraction=None, error=None):
    from .vehicle_imports import build_vehicle_document_preview
    row = Draft.query.filter_by(id=draft_id, status='reading').with_for_update().first()
    if not row or metadata(row.result_json).get('token') != token:
        db.session.rollback()
        return False
    job = metadata(row.result_json)
    if error is None:
        try:
            row.status = 'preview'
            preview = build_vehicle_document_preview(row, extraction,
                company_code=row.company_code, username=row.created_by_username)
            if not preview.get('records'):
                raise ValueError('OCR_NO_RECORDS')
            preview['routing_notice'] = job.get('routing_notice', '')
            row.preview_json = encode(preview)
        except Exception as exc:
            error = exc
    if error is not None:
        row.status = 'read_error'
        row.preview_json = '{}'
        job.update(phase='error', message=failure_message(error))
    else:
        job.update(phase='complete', message='')
    job.pop('token',None)
    job.pop('lease_until',None)
    job['updated_at'] = now().isoformat()
    row.result_json = result(job)
    db.session.commit()
    return True


def route_detection(draft_id, token, detection):
    """Fence classification and rerouting with the same lease as extraction."""
    from document_type_detection import KINDS
    from .import_flow import completed_document
    validate_detection(detection)
    row = Draft.query.filter_by(id=draft_id, status='reading').with_for_update().first()
    if not row or metadata(row.result_json).get('token') != token:
        db.session.rollback()
        return None
    job = metadata(row.result_json)
    job['detection'] = detection
    kinds = detection['types']
    if not detection['supported'] or detection['certainty'] != 'clear' or not kinds:
        row.status = 'type_review'
        row.preview_json = '{}'
        job.update(phase='type_review', message='資料の種類を確認してください。原本は保存されています。')
        for key in ('token', 'lease_until'):
            job.pop(key, None)
        row.result_json = result(job)
        db.session.commit()
        return None
    requested = job.get('requested_type', row.document_type)
    for position, kind in enumerate(kinds[1:], 1):
        child_id = str(uuid5(UUID(row.id), 'kind:' + kind + ':' + str(job.get('generation', 0))))
        if db.session.get(Draft, child_id) is None:
            child_job = {'phase':'queued', 'attempts':0, 'generation':0,
                'position':job.get('position', 0) + position / 10, 'updated_at':now().isoformat(),
                'requested_type':requested, 'forced_type':True,
                'routing_notice':'混在する資料から、' + KINDS[kind] + 'を読み取りました。'}
            db.session.add(Draft(id=child_id, batch_id=row.batch_id, company_code=row.company_code,
                created_by_username=row.created_by_username, document_type=kind,
                source_filename=row.source_filename, source_file=store_source(row.company_code,row.source_sha256,row.source_file), source_sha256=row.source_sha256,
                status='queued', preview_json='{}', result_json=result(child_job)))
    kind = kinds[0]
    row.document_type = kind
    job['routing_notice'] = ('混在する資料から、' + KINDS[kind] + 'を読み取りました。' if len(kinds) > 1 else
        KINDS[kind] + 'として読み取りました。' if kind != requested else job.get('routing_notice', ''))
    if completed_document(row.company_code, kind, row.source_sha256):
        row.status = 'skipped'
        job.update(phase='complete', message='この種類の資料は登録済みのため、今回の取込から除外しました。')
        for key in ('token', 'lease_until'):
            job.pop(key, None)
        row.result_json = result(job)
        db.session.commit()
        return None
    job['phase'] = 'reading'
    row.result_json = result(job)
    db.session.commit()
    return kind


def process_one(app):
    """One file at a time. No web request or user session is held while AI works."""
    import threading
    with app.app_context():
        claimed = claim_next()
        if not claimed:
            db.session.remove()
            return False
        draft_id, token = claimed
        row = Draft.query.filter_by(id=draft_id, status='reading').first()
        if not row or metadata(row.result_json).get('token') != token:
            db.session.remove()
            return True
        company = Company.query.filter_by(company_code=row.company_code, active=True).first()
        user = User.query.filter_by(company_code=row.company_code, username=row.created_by_username).first()
        allowed = (company is not None and user is not None
                   and not user.login_locked and user.role in {'admin', 'itc'})
        source, filename, kind, digest = row.source_file, row.source_filename, row.document_type, row.source_sha256
        forced = metadata(row.result_json).get('forced_type', False)
        db.session.remove()
    stopped = threading.Event()
    lost = threading.Event()
    update_lock = threading.Lock()

    def heartbeat():
        while not stopped.wait(15):
            with app.app_context():
                try:
                    with update_lock:
                        if not renew(draft_id, token):
                            lost.set()
                            return
                except Exception:
                    db.session.rollback()
                    app.logger.exception('OCR job heartbeat failed: %s', draft_id)
                finally:
                    db.session.remove()

    def progress(update):
        if lost.is_set():
            raise RuntimeError('JOB_LEASE_LOST')
        with app.app_context():
            try:
                with update_lock:
                    if not renew(draft_id, token, update):
                        lost.set()
                        raise RuntimeError('JOB_LEASE_LOST')
            finally:
                db.session.remove()

    keeper = threading.Thread(target=heartbeat, daemon=True, name='ocr-lease')
    keeper.start()
    extraction, error = None, None
    try:
        if not allowed:
            raise ValueError('OWNER_UNAVAILABLE')
        if hashlib.sha256(source).hexdigest() != digest:
            raise ValueError('SOURCE_CHANGED')
        from .vehicle_imports import vehicle_document_extractor
        detection = ({'types':[kind], 'certainty':'clear', 'supported':True, 'method':'manual'} if forced else
            detect_document_types(source, filename, progress))
        with app.app_context():
            try:
                with update_lock:
                    kind = route_detection(draft_id, token, detection)
            finally:
                db.session.remove()
        if kind is None:
            return True
        with app.app_context():
            extraction = vehicle_document_extractor(kind)(source, filename=filename, progress_callback=progress)
    except Exception as exc:
        error = exc
        app.logger.error('OCR job failed: %s (%s)', draft_id, type(exc).__name__)
    finally:
        stopped.set()
        keeper.join(timeout=2)
    if not lost.is_set():
        with app.app_context():
            try:
                finish(draft_id, token, extraction, error)
            finally:
                db.session.remove()
    return True


def batch_status(batch_id, company_code, username):
    rows = lightweight_query().filter_by(batch_id=batch_id, company_code=company_code,
                                          created_by_username=username).all()
    rows = [row for row in rows if not receipt_hidden(row.result_json)]
    if not rows:
        return None
    rows.sort(key=lambda row:(metadata(row.result_json).get('position',0),row.id))
    entries = []
    for row in rows:
        job = metadata(row.result_json)
        entries.append({'id':row.id, 'filename':row.source_filename, 'status':row.status,
            'document_type':row.document_type,
            'phase':job.get('phase',row.status), 'message':job.get('message',''),
            'received_lines':job.get('received_lines',0), 'ignored_files':job.get('ignored_files', [])})
    succeeded = sum(row.status in {'preview','completed','skipped'} for row in rows)
    failed = sum(row.status == 'read_error' for row in rows)
    active = sum(row.status in ACTIVE for row in rows)
    needs_review = sum(row.status == 'type_review' for row in rows)
    return {'batch_id':batch_id, 'files':entries, 'total':len(rows), 'succeeded':succeeded,
            'failed':failed, 'needs_review':needs_review, 'completed':len(rows)-active, 'finished':active==0,
            'preview_ready':active==0 and any(row.status=='preview' for row in rows)}


def retry_failed(batch_id, company_code, username):
    rows = lightweight_query().filter_by(batch_id=batch_id, company_code=company_code,
        created_by_username=username, status='read_error').all()
    count = 0
    for row in rows:
        old = row.result_json
        job = metadata(old)
        job.update(phase='queued', attempts=0, message='', updated_at=now().isoformat())
        count += Draft.query.filter_by(id=row.id, status='read_error', result_json=old).update(
            {'status':'queued', 'result_json':result(job)}, synchronize_session=False)
    db.session.commit()
    return count
