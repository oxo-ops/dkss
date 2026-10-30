"""Read-only kind identities for the independent inspection contract.

The legacy 12month storage value cannot by itself identify a vehicle inspection.
Do not rewrite it, infer from expiry dates, or discard authenticated confirmation
merely because an old row has no newly introduced marker.
"""
import json
from dataclasses import dataclass


PERIODIC_STORAGE_KIND = 'periodic_12month'
NEW_STORAGE_KINDS = {
    '3month': '3month', '12month': PERIODIC_STORAGE_KIND,
    'vehicle_inspection': 'vehicle_inspection', 'ad_hoc': 'ad_hoc',
}
PERIODIC_LABELS = frozenset({'12か月点検', '12か月定期点検', '12ヶ月点検', '12ヶ月定期点検'})


@dataclass(frozen=True)
class KindIdentity:
    kind: str | None
    basis: str

    @property
    def confirmed(self):
        return self.kind is not None


def new_storage_kind(kind):
    """For validated new writers only; not a legacy-row migration."""
    if not isinstance(kind, str) or kind not in NEW_STORAGE_KINDS:
        raise ValueError('Unsupported inspection kind')
    return NEW_STORAGE_KINDS[kind]


def stored_kind_identity(kind):
    """Resolve only storage values whose meanings are intrinsically separate."""
    if not isinstance(kind, str):
        return KindIdentity(None, 'unsupported_kind')
    if kind == PERIODIC_STORAGE_KIND:
        return KindIdentity('12month', 'independent_storage')
    if kind in {'3month', 'vehicle_inspection', 'ad_hoc'}:
        return KindIdentity(kind, 'stored_kind')
    return KindIdentity(None, 'legacy_evidence_required' if kind == '12month' else 'unsupported_kind')


def _object(raw):
    try:
        parsed = json.loads(raw or '{}')
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, ValueError):
        return None


def document_kind_identity(record, draft, *, company_code, vehicle_id):
    """Resolve a fact through its company-scoped confirmed original.

This recognizes the existing human-confirmation contract for an unambiguous
12-month source. A conflicting or mixed original is not silently reclassified.
The caller must retain an unconfirmed row and resolve other evidence sources;
an inconclusive result here is not authorization to invalidate its history.
"""
    if (record is None or record.company_code != company_code
            or record.vehicle_record_id != vehicle_id):
        return KindIdentity(None, 'record_boundary')
    explicit = stored_kind_identity(record.inspection_type)
    if explicit.confirmed:
        return explicit
    if record.inspection_type != '12month':
        return explicit
    if (draft is None or record.source_draft_id != draft.id
            or draft.company_code != company_code or draft.document_type != 'inspection'
            or draft.status != 'completed'):
        return KindIdentity(None, 'source_boundary')
    index = record.source_record_index
    if type(index) is not int or index < 0:
        return KindIdentity(None, 'source_index')
    details, preview, result = (_object(record.details_json), _object(draft.preview_json), _object(draft.result_json))
    if any(value is None for value in (details, preview, result)):
        return KindIdentity(None, 'source_json')
    originals, registered = preview.get('original_records'), result.get('records')
    if not isinstance(originals, list) or index >= len(originals) or not isinstance(registered, list):
        return KindIdentity(None, 'source_index')
    original = originals[index]
    raw = details.get('inspection_type_raw')
    if (not isinstance(original, dict) or not isinstance(raw, str)
            or raw not in PERIODIC_LABELS or original.get('inspection_type_raw') != raw
            or original.get('inspection_type') != '12month'
            or details.get('inspection_type') != '12month'
            or details.get('vehicle_record_id') != vehicle_id):
        return KindIdentity(None, 'source_kind_not_established')
    matches = [row for row in registered if isinstance(row, dict) and row.get('record_index') == index]
    if (len(matches) != 1 or type(matches[0].get('record_index')) is not int
            or matches[0].get('record_id') != record.id
            or matches[0].get('vehicle_record_id') != vehicle_id
            or matches[0].get('document_type') != 'inspection'):
        return KindIdentity(None, 'registration_boundary')
    return KindIdentity('12month', 'confirmed_document')
