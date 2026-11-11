"""Original certificate dates and registered updates, never a legal decision.

A same-page literal date is not an effective legal deadline. This reader does
not infer extensions, exceptions, document authenticity, or the absence of a
later unreceived certificate. It neither alters master dates nor emits scores.
"""
from copy import deepcopy
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo
import hashlib
from io import BytesIO
import json
import re
import unicodedata

from vehicle_priority_inputs import fingerprint

VERSION = 'certificate-expiry-original-v2'
SUBJECT = '車検証の有効期間満了'
VEHICLE_KEYS = ('chassis_number', 'model_code', 'type', 'body_type', 'office',
    'plate_area', 'plate_class', 'plate_kana', 'plate_number', 'inspection_expiry')
MAX_DOCUMENT_INDEX = 500
MAX_DOCUMENTS = 20
MAX_EXECUTIONS = 250
MAX_ORIGINAL_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024
LABELS = ('有効期間の満了する日', '有効期間満了日')
DATE_TOKEN = re.compile(r'(?:(?:令和|平成|昭和)(?:元|[0-9]{1,2})年[0-9]{1,2}月[0-9]{1,2}日|'
    r'[0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日|[0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2})(?![0-9])')


def _norm(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or ''))).translate(
        str.maketrans({'‐': '-', '－': '-', '−': '-'}))


def _object(raw):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _iso(value):
    try:
        parsed = date.fromisoformat(value)
        return parsed if parsed.isoformat() == value else None
    except (ValueError, TypeError):
        return None


def _literal_day(value):
    era = re.fullmatch(r'(令和|平成|昭和)(元|[0-9]{1,2})年([0-9]{1,2})月([0-9]{1,2})日', value)
    try:
        if era:
            start, stop = {'令和': (date(2019, 5, 1), None), '平成': (date(1989, 1, 8), date(2019, 4, 30)),
                           '昭和': (date(1926, 12, 25), date(1989, 1, 7))}[era[1]]
            year = 1 if era[2] == '元' else int(era[2])
            if year < 1:
                return None
            day = date(start.year + year - 1, int(era[3]), int(era[4]))
            return day if day >= start and (stop is None or day <= stop) else None
        parts = re.fullmatch(r'([0-9]{4})(?:年|[-/])([0-9]{1,2})(?:月|[-/])([0-9]{1,2})日?', value)
        return date(*(int(parts[i]) for i in (1, 2, 3))) if parts else None
    except ValueError:
        return None


def verify_certificate_expiry_literal(original, extraction, expected_identity):
    """Verify the labelled date beside this one vehicle, not a date elsewhere."""
    result = {'version': VERSION, 'status': 'source_unverified', 'literal_verified': False,
        'expiry_on': None, 'pages': [], 'quotes': [],
        'scope': 'literal_same_page_only_not_authenticity_or_legal_validity',
        'effective_legal_deadline_verified': False}
    if not isinstance(original, bytes) or not 1 <= len(original) <= MAX_ORIGINAL_BYTES:
        return result
    result['document_checksum'] = hashlib.sha256(original).hexdigest()
    identity = {name: _norm((expected_identity or {}).get(name)) for name in ('chassis_number', 'model_code')}
    if not all(identity.values()) or not isinstance(extraction, dict) or not isinstance(extraction.get('vehicle'), dict):
        return result
    candidate = extraction['vehicle'].get('inspection_expiry')
    if candidate is not None and _iso(candidate) is None:
        return result
    if any(_norm(extraction['vehicle'].get(key)) != value for key, value in identity.items()):
        result['status'] = 'vehicle_identity_mismatch'; return result
    if not original.startswith(b'%PDF-'):
        result['status'] = 'literal_text_not_available'; return result
    matches = []
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(original), strict=False)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 10:
            return result
        for number, page in enumerate(reader.pages, 1):
            contents = page.get_contents()
            if contents is not None and len(contents.get_data()) > 5 * 1024 * 1024:
                return result
            raw = page.extract_text() or ''
            if len(raw) > 200000:
                return result
            text = _norm(raw)
            if re.search(r'架空|見本|実証明不可|証明には使用できません|合成試験専用|SAMPLE|SPECIMEN|FICTIONAL|NOTVALID', text, re.I):
                result['status'] = 'explicit_test_or_nonofficial_original'; return result
            token = lambda value: re.search(r'(?<![A-Z0-9])' + re.escape(value) + r'(?![A-Z0-9])', text, re.I)
            detected = re.findall(r'[A-Z][A-Z0-9]{2,12}-[0-9]{4,12}(?![A-Z0-9])', text, re.I)
            if (not all(token(v) for v in identity.values()) or text.count('車台番号') != 1
                    or len(set(detected)) != 1 or _norm(detected[0]) != identity['chassis_number']):
                continue
            counts = [(label, text.count(label)) for label in LABELS]
            if sum(count for _, count in counts) != 1:
                continue
            label = next(label for label, count in counts if count)
            tail = text.split(label, 1)[1].lstrip(':')
            match = DATE_TOKEN.match(tail)
            day = _literal_day(match[0]) if match else None
            if day is not None:
                matches.append((number, day.isoformat(), label + match[0]))
    except Exception:
        return result
    values = {value for _, value, _ in matches}
    if len(values) != 1:
        result['status'] = 'ambiguous_or_unreadable_expiry'; return result
    literal = next(iter(values))
    if candidate is not None and candidate != literal:
        result['status'] = 'extracted_date_conflicts_with_original'; return result
    result.update(status='literal_same_page_matched', literal_verified=True, expiry_on=literal,
        pages=[page for page, _, _ in matches], quotes=[quote for _, _, quote in matches])
    return result


def _read_certificate_expiry_sources(vehicle, *, as_of):
    """Read scoped saved originals and manual update relations without mutation.

    Coverage deliberately excludes unreceived documents and does not establish
    legal-extension applicability. All output remains non-emitting for floor60.
    """
    from .models import (Vehicle, VehicleDocumentImportDraft as Draft, VehicleDocumentSource as Source,
        VehiclePeriodicInspectionRecord as Record, db)
    from .vehicle_inspection_plans_models import get_models
    from sqlalchemy.exc import SQLAlchemyError
    _, _, Execution, Evidence = get_models(db)
    output = {'version': VERSION, 'company_code': vehicle.company_code, 'vehicle_id': vehicle.id,
        'originals': [], 'registered_updates': [], 'registered_expiry': None,
        'effective_legal_deadline': None, 'effective_legal_deadline_verified': False,
        'coverage': 'linked_certificates_and_registered_manual_execution_evidence',
        'inspection_records': [], 'missing_conditions': [], 'vehicle_facts': {key: getattr(vehicle, key, None) for key in VEHICLE_KEYS}}
    def held(message):
        output['originals'], output['registered_updates'] = [], []
        output['missing_conditions'] = [message]
        return output
    if type(as_of) is not date:
        return held('基準日を確認要')
    if db.session.new or db.session.dirty or db.session.deleted:
        return held('未保存変更があるため原本・更新関係の照合を保留しています')
    try:
        with db.session.no_autoflush:
            current = db.session.query(Vehicle.id, Vehicle.chassis_number, Vehicle.model_code,
                Vehicle.inspection_expiry).filter_by(company_code=vehicle.company_code, id=vehicle.id, deleted=False).first()
            if current is None:
                return held('会社・車両の現在登録を確認できません')
            output['registered_expiry'] = current.inspection_expiry
            identity = {key: getattr(current, key) for key in ('chassis_number', 'model_code')}
            # Only binding metadata is indexed across the company; other
            # vehicles' originals and extraction payloads are never fetched.
            content = db.case((db.func.length(Draft._source_file) > 0, Draft._source_file), else_=Source.content)
            index = db.session.query(Draft.id, Draft.result_json, db.func.length(content).label('size')).outerjoin(
                Source, (Source.company_code == Draft.company_code) & (Source.sha256 == Draft.source_sha256)).filter(
                Draft.company_code == vehicle.company_code, Draft.document_type == 'certificate',
                Draft.status == 'certificate_linked').order_by(Draft.id).limit(MAX_DOCUMENT_INDEX + 1).all()
            if len(index) > MAX_DOCUMENT_INDEX:
                return held('車検原本の索引が読取上限を超えたため部分照合はしません')
            selected = []
            for value in index:
                binding = _object(value.result_json)
                if binding and type(binding.get('vehicle_record_id')) is int and binding['vehicle_record_id'] == vehicle.id:
                    selected.append(value)
            if (len(selected) > MAX_DOCUMENTS or any(not v.size or v.size > MAX_ORIGINAL_BYTES for v in selected)
                    or sum(v.size for v in selected) > MAX_TOTAL_BYTES):
                return held('対象原本の件数・容量が読取上限を超えたため部分照合はしません')
            originals = db.session.query(Draft.id, Draft.result_json, Draft.preview_json, content.label('source_file'),
                Draft.source_sha256, Draft.created_at, Draft.completed_at, Draft.source_filename).outerjoin(
                Source, (Source.company_code == Draft.company_code) & (Source.sha256 == Draft.source_sha256)).filter(
                Draft.company_code == vehicle.company_code, Draft.document_type == 'certificate',
                Draft.status == 'certificate_linked', Draft.id.in_([v.id for v in selected])).order_by(Draft.created_at, Draft.id).all() if selected else []
            normalized_identity = {key: _norm(value) for key, value in identity.items()}
            for value in originals:
                binding = _object(value.result_json)
                if (not binding or type(binding.get('vehicle_record_id')) is not int
                        or binding['vehicle_record_id'] != vehicle.id or binding.get('identity') != normalized_identity
                        or not isinstance(value.source_file, bytes)
                        or hashlib.sha256(value.source_file).hexdigest() != value.source_sha256):
                    return held('原本の会社・車両・版・checksumとの一致を確認できません')
                saved = _object(value.preview_json) or {}
                result = verify_certificate_expiry_literal(value.source_file, saved.get('certificate_extraction'), identity)
                result.update(document_id=value.id, filename=value.source_filename, registered_at=str(value.created_at),
                    linked_at=str(value.completed_at) if value.completed_at else None,
                    matches_current_registered_expiry=bool(result['literal_verified'] and result['expiry_on'] == current.inspection_expiry))
                output['originals'].append(result)
            rows = db.session.query(Execution.id, Execution.kind, Execution.performed_date,
                Execution.company_code, Execution.vehicle_record_id, Execution.plan_id, Execution.source_record_id,
                Execution.created_at, Execution.created_by, Evidence.new_expiry, Evidence.previous_expiry,
                Evidence.document_id, Evidence.confirmation, Evidence.attachment_confirmation,
                Evidence.attached_at, Evidence.attached_by).outerjoin(Evidence,
                (Evidence.execution_id == Execution.id) & (Evidence.company_code == Execution.company_code)).filter(
                Execution.company_code == vehicle.company_code, Execution.vehicle_record_id == vehicle.id).order_by(
                Execution.performed_date, Execution.id).limit(MAX_EXECUTIONS + 1).all()
            if len(rows) > MAX_EXECUTIONS:
                return held('車検更新の登録履歴が読取上限を超えたため部分照合はしません')
            from flask import current_app
            service = current_app.extensions.get('inspection_plan_sync')
            if service is None:
                return held('既存の点検・車検区分の照合機能を利用できません')
            records = Record.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id).order_by(
                Record.inspection_date, Record.id).limit(MAX_EXECUTIONS + 1).all()
            if len(records) > MAX_EXECUTIONS:
                return held('点検・車検原記録が読取上限を超えるため部分照合しません')
            relevant_ids = set()
            for record in records:
                resolved = service.record_kind(record)
                if resolved in {'3month', '12month', 'ad_hoc'}:
                    continue
                if resolved != 'vehicle_inspection':
                    return held('車検か定期点検か未確認の原記録があります')
                relevant_ids.add(record.id)
                output['inspection_records'].append({key: getattr(record, key) for key in (
                    'id', 'inspection_type', 'inspection_date', 'completion_date', 'next_inspection_date',
                    'source_draft_id', 'source_record_index', 'details_json')})
            by_document = {v['document_id']: v for v in output['originals']}
            linked_ids = set()
            for row in rows:
                resolved = service.execution_kind(row)
                if resolved in {'3month', '12month', 'ad_hoc'}:
                    continue  # A confirmed 12-month inspection never becomes a certificate expiry.
                if resolved != 'vehicle_inspection':
                    return held('車検か定期点検か未確認の実施記録があります')
                if row.source_record_id:
                    match = next((r for r in records if r.id == row.source_record_id), None)
                    if match is None or row.source_record_id not in relevant_ids or match.inspection_date != row.performed_date:
                        return held('車検実施と原記録の会社・車両・実施日が一致しません')
                    linked_ids.add(row.source_record_id)
                document = by_document.get(row.document_id)
                performed, new = _iso(row.performed_date), _iso(row.new_expiry)
                document_match = bool(document and document['literal_verified']
                    and document['expiry_on'] == row.new_expiry and performed and new and performed < new and performed <= as_of)
                output['registered_updates'].append({
                    'execution_id': row.id, 'performed_date': row.performed_date,
                    'created_at': row.created_at, 'created_by': row.created_by,
                    'attached_at': row.attached_at, 'attached_by': row.attached_by,
                    'previous_expiry': row.previous_expiry, 'new_expiry': row.new_expiry,
                    'document_id': row.document_id, 'literal_expiry_matches': document_match,
                    'recorded_confirmation': row.confirmation,
                    'attachment_confirmation': row.attachment_confirmation,
                    'confirmation_scope': 'inspection_kind_and_performed_date_only',
                    'source_fingerprint': fingerprint(list(row)),
                    'source_url': f'/vehicle/inspection-plans/executions/{row.id}/source' if document_match else None})
            if relevant_ids - linked_ids:
                return held('車検原記録に対応する満了日更新・実施原本のつながりを確認してください')
    except (SQLAlchemyError, ValueError, TypeError, AttributeError):
        return held('原本・更新関係を読み取れないため法的期限の確認を保留しています')
    valid = [v for v in output['originals'] if v['literal_verified']]
    if not valid:
        output['missing_conditions'].append('同じ車両の原本に記載された満了日そのものとの照合を確認要')
    if valid and not any(v['matches_current_registered_expiry'] for v in valid):
        output['missing_conditions'].append('原本の満了日と現在登録の満了日が一致していません')
    if len({v['expiry_on'] for v in valid}) > 1:
        output['missing_conditions'].append('複数原本の満了日が異なります。アップロード順や最大日付だけでは最新有効版を選びません')
    if any(not v['literal_expiry_matches'] for v in output['registered_updates']):
        output['missing_conditions'].append('登録された車検更新の満了日と、対応する原本値の照合を確認要')
    output['missing_conditions'].extend([
        '後続の車検実施・更新・訂正を含めて現在有効な原本かを確認要',
        '公示による延長・適用地域・例外を含む実効的な法的期限は、この記載日だけでは確定しません'])
    return output


class CertificateUnavailable(ValueError):
    """Incomplete or conflicting sources cannot confirm an effective deadline."""


def _today():
    return datetime.now(ZoneInfo('Asia/Tokyo')).date()


def read_certificate_expiry_sources(vehicle, *, as_of=None):
    """Fresh read-only snapshot, including company-scoped compacted originals."""
    from flask import current_app
    from sqlalchemy.exc import SQLAlchemyError
    from .models import Vehicle, db
    as_of = _today() if as_of is None else as_of
    company, vehicle_id = vehicle.company_code, vehicle.id
    empty = {'version': VERSION, 'company_code': company, 'vehicle_id': vehicle_id,
        'originals': [], 'registered_updates': [], 'registered_expiry': None,
        'effective_legal_deadline': None, 'effective_legal_deadline_verified': False,
        'missing_conditions': [], 'vehicle_facts': {}}
    if type(as_of) is not date or as_of > _today():
        empty['missing_conditions'] = ['基準日は日本時間の本日以前を指定してください']; return empty
    if db.session.new or db.session.dirty or db.session.deleted:
        empty['missing_conditions'] = ['未保存変更があるため原本・更新関係の照合を保留しています']; return empty
    try:
        with current_app._get_current_object().app_context():
            with db.session.no_autoflush:
                fresh = Vehicle.query.filter_by(company_code=company, id=vehicle_id, deleted=False).first()
                if fresh is None:
                    raise CertificateUnavailable('会社・車両の現在登録を確認できません')
                return _read_certificate_expiry_sources(fresh, as_of=as_of)
    except (SQLAlchemyError, ValueError, TypeError, AttributeError) as error:
        empty['missing_conditions'] = [str(error) if isinstance(error, CertificateUnavailable)
            else '原本・更新関係を読み取れません']; return empty


# Read from MLIT's 2026-06-01 statute collection. These excerpts explain the
# bounded scope, not an automatically maintained list of extensions/exceptions.
LEGAL_BASIS = {
    'url': 'https://www.mlit.go.jp/jidosha/content/001740686.pdf#page=121',
    'issuer': '国土交通省', 'title': '道路運送車両法 第58条・第61条の2・第62条',
    'version': '法令試験条文集 2026-06-01更新（2026-11-11照合）',
    'quote': ('第61条の2第2項（抜粋）：自動車検査証の有効期間は、公示の定めるところにより伸長したものとみなす。'
        '\n第62条第1項（抜粋）：自動車検査証の有効期間の満了後も当該自動車を使用しようとするときは、'
        '当該自動車を提示して、国土交通大臣の行う継続検査を受けなければならない。'),
    'scope': '自動車検査証の有効期間満了のみ。定期点検期限、運行可否、延長日付の計算は対象外。',
}
STATEMENTS = (
    ('official_current_record_confirmed', '選択した原本は架空・取込試験用ではなく、この実車の自動車検査証または自動車検査証記録事項です。電子車検証では最新の電子記録の満了日と一致することを確認しました'),
    ('latest_updates_confirmed', '表示した原本と更新履歴に加え、未登録の後続車検・更新・訂正も確認し、選択原本が現在の満了日を示すことを確認しました'),
    ('legal_scope_confirmed', '車両区分と使用状況を確認し、この車両が自動車検査証の有効期間の適用対象であることを確認しました'),
    ('extension_applicability_confirmed', '使用の本拠と対象日について現在の公示・延長・例外を確認し、表示された満了日が変更されず適用されることを確認しました。不明または延長が適用される場合は確認しません'),
)
NOTICE = ('対応対象は、原本の満了日がそのまま適用される車検だけです。'
    '延長や例外が適用される場合・不明な場合は確認せず、元記録を確認してください。'
    '満了日の到来を対応優先度に使いますが、当日失効・運行禁止とは判定しません。'
    'この任意確認は日本時間の確認日当日の適用関係を記録します。翌日も通常利用を続けられ、未確認を低い点数へ変えません。')


def _uuid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


def _source_url(vehicle_id, document_id):
    return f'/vehicle/karte/{vehicle_id}/priority-confirmations/certificates/{document_id}/source'


def _candidate(snapshot, document_id):
    """Require a connected sequence, never largest date or latest upload wins."""
    originals = snapshot['originals']
    selected = [row for row in originals if row['document_id'] == document_id]
    if len(selected) != 1 or not selected[0]['literal_verified']:
        raise CertificateUnavailable('選択原本の同一車両・満了日を照合できません')
    selected = selected[0]
    if not selected['matches_current_registered_expiry']:
        raise CertificateUnavailable('選択原本と現在登録の満了日が一致していません')
    if any(not row['literal_verified'] for row in originals):
        raise CertificateUnavailable('他の保存原本に未照合・競合があるため、現在の原本を確定できません')
    updates = snapshot['registered_updates']
    if any(not row['literal_expiry_matches'] or not row['recorded_confirmation'] for row in updates):
        raise CertificateUnavailable('更新履歴の実施・新満了日・対応原本の照合を確認してください')
    # Same-day alternate updates are conflicts, not an ordering tie-breaker.
    if len({row['performed_date'] for row in updates}) != len(updates):
        raise CertificateUnavailable('同じ実施日の車検更新が競合しています')
    for before, after in zip(updates, updates[1:]):
        if after['previous_expiry'] != before['new_expiry']:
            raise CertificateUnavailable('車検更新の前後満了日が連続していません')
    if updates and updates[-1]['new_expiry'] != selected['expiry_on']:
        raise CertificateUnavailable('後続の車検更新と選択原本の満了日が一致しません')
    connected = {selected['expiry_on']}
    for row in reversed(updates):
        if row['new_expiry'] not in connected:
            raise CertificateUnavailable('選択原本と車検更新のつながりを確認できません')
        if row['previous_expiry'] is not None:
            if _iso(row['previous_expiry']) is None:
                raise CertificateUnavailable('更新前の満了日を確認できません')
            connected.add(row['previous_expiry'])
    if not {row['expiry_on'] for row in originals} <= connected:
        raise CertificateUnavailable('異なる原本の満了日と更新履歴の対応を確認できません。最大日付やアップロード順では選びません')
    return selected


def certificate_confirmation_options(vehicle, *, as_of=None):
    snapshot = read_certificate_expiry_sources(vehicle, as_of=as_of)
    options, errors = [], []
    for row in snapshot['originals']:
        try:
            selected = _candidate(snapshot, row['document_id'])
            options.append({'value': row['document_id'],
                'label': f"{selected['filename']} / 満了日 {selected['expiry_on']}",
                'source_url': _source_url(vehicle.id, row['document_id'])})
        except CertificateUnavailable as error:
            errors.append(str(error))
    return {'fields': [{'key': 'document_id', 'label': '現在の満了日を示す原本（車検のみ）',
        'type': 'select', 'options': options}],
        'missing_conditions': list(dict.fromkeys([NOTICE, *([] if options else snapshot['missing_conditions'] + errors)]))}


def _preview(snapshot, selection, checked_on):
    selected = _candidate(snapshot, selection['document_id'])
    sid = 'certificate:' + selected['document_id']
    result = {'kind': 'legal_deadline', 'selection': {'document_id': selected['document_id']},
        'subject': SUBJECT, 'source_ids': [sid],
        'sources': {'snapshot': deepcopy(snapshot), 'selected_original': deepcopy(selected),
            'legal_basis': deepcopy(LEGAL_BASIS), 'applicability_checked_on': checked_on.isoformat(),
            'timezone': 'Asia/Tokyo', 'notice': NOTICE},
        'source_links': {sid: {'label': '選択した車検原本', 'url': _source_url(snapshot['vehicle_id'], selected['document_id'])}},
        'statements': [{'key': key, 'label': label} for key, label in STATEMENTS]}
    updates = snapshot['registered_updates']
    result['display_sources'] = [
        {'label': '選択原本の記載', 'text': '\n'.join(selected['quotes']) + '（原文の文字列照合のみ）',
         'url': _source_url(snapshot['vehicle_id'], selected['document_id'])},
        {'label': '現在登録の満了日', 'text': snapshot['registered_expiry']},
        {'label': '登録済みの車検更新', 'text': '\n'.join(
            f"実施日 {row['performed_date']} / 前満了日 {row['previous_expiry'] or '記録なし'} → 新満了日 {row['new_expiry']} / 原本照合済み"
            for row in updates) if updates else '登録された車検更新はありません。未登録の更新がないことは意味しません。'},
        {'label': '対象・確認日', 'text': f'{SUBJECT} / {checked_on.isoformat()}（日本時間）\n' + NOTICE},
        {'label': '法令の根拠と公示延長の注意', 'text': LEGAL_BASIS['quote'] + '\n' + LEGAL_BASIS['scope'],
         'url': LEGAL_BASIS['url']},
    ]
    result['fingerprint'] = fingerprint(result)
    return result


def preview_certificate_confirmation(vehicle, selection, *, as_of=None):
    """Preview literal facts, never user approval or effective-date inference.

    The common workflow validates every fixed statement, actor, audit chain,
    withdrawal and exact current fingerprint. The date belongs in that fingerprint
    because unseen new notices cannot be silently treated as non-applicable.
    """
    as_of = _today() if as_of is None else as_of
    if (not isinstance(selection, dict) or set(selection) != {'document_id'}
            or not _uuid(selection['document_id']) or type(as_of) is not date or as_of > _today()):
        raise CertificateUnavailable('確認対象の原本を選択してください')
    snapshot = read_certificate_expiry_sources(vehicle, as_of=as_of)
    return _preview(snapshot, selection, as_of)


def certificate_confirmation_inputs(preview, *, event_id, confirmed_on, as_of=None):
    """Core inputs ONLY after common active-confirmation authentication/recheck.

    Date-only means the Japan calendar day has arrived, not that the certificate
    has already expired at midnight. No operation decision is emitted or changed.
    """
    from vehicle_priority_assessment import Scope, Evidence, Reference, TimingFact
    as_of = _today() if as_of is None else as_of
    if (type(event_id) is not int or event_id <= 0 or type(confirmed_on) is not date
            or type(as_of) is not date or confirmed_on != as_of or as_of > _today()
            or not isinstance(preview, dict) or preview.get('kind') != 'legal_deadline'):
        raise CertificateUnavailable('法的期限の確認日・監査識別を確認してください')
    sources = preview['sources']
    if (sources['applicability_checked_on'] != as_of.isoformat()
            or _preview(sources['snapshot'], preview['selection'], as_of) != preview):
        raise CertificateUnavailable('原本・更新・適用確認日が変わったため再確認してください')
    expiry = _iso(sources['selected_original']['expiry_on'])
    scope = Scope(sources['snapshot']['company_code'], sources['snapshot']['vehicle_id'], SUBJECT)
    subject_event = 'certificate-expiry:' + preview['selection']['document_id']
    sid, audit = preview['source_ids'][0], f'priority_confirmation:{event_id}'
    evidence = {
        sid: Evidence(sid, scope, confirmed_on, subject_event,
            '\n'.join(sources['selected_original']['quotes']), True, 'record', 'current'),
        audit: Evidence(audit, scope, confirmed_on, subject_event,
            '原本・最新更新・法適用・公示延長と例外を人が確認: ' + expiry.isoformat(), True, 'record', 'current')}
    basis = sources['legal_basis']
    rid = 'government:certificate-validity:20260601'
    reference = Reference(rid, basis['url'], basis['issuer'], basis['title'], basis['version'],
        basis['quote'], 'government', True, True, False)
    arrived = expiry <= as_of
    return {'scope': scope, 'event_id': subject_event, 'facts': (),
        'timings': (TimingFact((sid, audit), (rid,), True, True, True, True, expiry, legal_deadline=True),) if arrived else (),
        'skip_assessment': not arrived, 'evidence': evidence, 'references': {rid: reference},
        'missing_conditions': (NOTICE, '適用確認は日本時間の確認日についてのものです。日付や原本・更新が変わった場合は再確認してください。')}


def read_certificate_confirmation_original(vehicle, document_id, *, as_of=None):
    """Company/vehicle/checksum-scoped source for the authenticated common GET."""
    from flask import current_app
    from .models import db, Vehicle, VehicleDocumentImportDraft as Draft
    if not _uuid(document_id):
        raise CertificateUnavailable('原本識別を確認できません')
    snapshot = read_certificate_expiry_sources(vehicle, as_of=as_of)
    selected = [row for row in snapshot['originals'] if row['document_id'] == document_id]
    if len(selected) != 1:
        raise CertificateUnavailable('同じ会社・車両の原本を確認できません')
    with current_app._get_current_object().app_context():
        with db.session.no_autoflush:
            draft = Draft.query.filter_by(company_code=vehicle.company_code, id=document_id,
                document_type='certificate', status='certificate_linked').first()
            fresh = Vehicle.query.filter_by(company_code=vehicle.company_code, id=vehicle.id, deleted=False).first()
            binding = _object(draft.result_json) if draft else None
            identity = {key: _norm(getattr(fresh, key, None)) for key in ('chassis_number', 'model_code')}
            raw = draft.source_file if draft else None
            if (fresh is None or not binding or type(binding.get('vehicle_record_id')) is not int
                    or binding['vehicle_record_id'] != vehicle.id or binding.get('identity') != identity
                    or not all(identity.values()) or not isinstance(raw, bytes)
                    or hashlib.sha256(raw).hexdigest() != selected[0]['document_checksum']):
                raise CertificateUnavailable('原本の版が変わったため再確認してください')
            return {'data': raw, 'filename': draft.source_filename, 'mimetype': 'application/pdf'}
