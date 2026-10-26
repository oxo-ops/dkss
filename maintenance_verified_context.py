"""Versioned, source-reviewed document context; separate from numerical maintenance rules.

No network, model calls or database writes. A reviewed edition is recognized by
its original-byte checksum, verified source, adopted anchor rule and literal
page quotations. Unknown editions fail closed without affecting existing rules.
This catalogue is a bounded initial adapter, not a general PDF understanding
engine or a vehicle-risk scoring model.
"""
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import re
import unicodedata

CONTEXT_VERSION = 'verified-document-context-v1'
CHECKSUM = '80a351761072cbc07a0a6a64f84c4ebf2fd247091c1241a3355b02029f60ba25'
SOURCE_URL = 'https://www.hino.co.jp/ts/vehicle_maintenance/pdf/296.pdf'
ANCHOR_QUOTE = '3カ月 または 15,000kmごと 点検'
REVIEWED = (
    {
        'context_id': 'air-dryer-function-20260914',
        'kind': 'component_function', 'source_page': 1,
        'source_quote': 'エアドライヤーはこの『水分』と『油分』を捕捉する重要な役割があります。',
        'meaning': '装置の役割を示す知識であり、現在の車両で機能低下が起きている証拠ではない。',
    },
    {
        'context_id': 'air-dryer-conditional-impact-20260914',
        'kind': 'conditional_impact', 'source_page': 1,
        'source_quote': 'エアドライヤーの乾燥剤およびフィルタを交換しないまま使用し続けると、エア経路に水分や油分が入り込み、ブレーキ装置等の故障を引き起こす恐れがあります。',
        'condition': '乾燥剤・フィルタを交換しないまま使用し、水分・油分がエア経路へ入り込む場合。',
        'meaning': '定期整備を怠った場合の影響を説明する資料上の知識。対象車両の交換未実施・故障・期限超過を示す実績ではない。',
    },
    {
        'context_id': 'air-dryer-daily-liquid-check-20260914',
        'kind': 'daily_inspection', 'source_page': 2,
        'source_quote': 'エアタンク内の液体がないことを確認',
        'action': 'エアタンク内の液体の有無を確認する。',
        'meaning': '同じ対象車両・仕様・排ガス記号の表に記載された日常点検。分解手順や数値基準は含まない。',
    },
    {
        'context_id': 'air-dryer-daily-discharge-check-20260914',
        'kind': 'daily_inspection', 'source_page': 2,
        'source_quote': 'エア圧充てん時のエア排出されることを確認',
        'action': 'エア圧充填時にエアが排出されることを確認する。',
        'meaning': '同じ対象車両・仕様・排ガス記号の表に記載された日常点検。分解手順や数値基準は含まない。',
    },
)

def normalize(value):
    value = unicodedata.normalize('NFKC', value)
    return re.sub(r'\s+', '', value.replace('\u00ad', '').replace('\u200b', ''))

@lru_cache(maxsize=2)
def reviewed_pages(original):
    if not isinstance(original, bytes) or len(original) > 4 * 1024 * 1024:
        return ()
    if sha256(original).hexdigest() != CHECKSUM:
        return ()
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(original), strict=False)
        if reader.is_encrypted or len(reader.pages) != 2:
            return ()
        result = []
        for page in reader.pages:
            stream = page.get_contents()
            if stream is not None and len(stream.get_data()) > 5 * 1024 * 1024:
                return ()
            text = page.extract_text() or ''
            if not text or len(text) > 200000:
                return ()
            result.append(normalize(text))
        return tuple(result)
    except Exception:
        # Context absence must not suppress a previously valid numerical rule.
        return ()

def get_verified_context(original, item):
    if not isinstance(item, dict) or item.get('source_kind') != 'メーカー公式資料':
        return []
    evidence = item.get('maintenance_rule_evidence') or {}
    if evidence.get('document_checksum') != CHECKSUM:
        return []
    source_id = item.get('source_id')
    if not isinstance(source_id, str) or not re.fullmatch(r'knowledge:[0-9]+', source_id):
        return []
    anchors = []
    for rule in evidence.get('rules', []):
        adoption = rule.get('analysis_adoption') or {}
        verification = rule.get('source_verification') or {}
        semantic = rule.get('semantic_review') or {}
        applicability = rule.get('vehicle_applicability') or {}
        states = evidence.get('public_document_states') or []
        # Reuse an actually adopted inspection rule, not manufacturer-name inference.
        if (rule.get('action') != 'inspect'
            or rule.get('source_page') != 2
            or normalize(str(rule.get('source_quote') or '')) != normalize(ANCHOR_QUOTE)
            or adoption.get('status') != 'adopted_for_analysis'
            or adoption.get('document_checksum') != CHECKSUM
            or adoption.get('document_id') != evidence.get('document_id')
            or adoption.get('knowledge_source_id') != source_id
            or adoption.get('source_url') != SOURCE_URL
            or not re.fullmatch(r'vehicle:[0-9]+', str(adoption.get('vehicle_source_id') or ''))
            or verification.get('status') != 'quote_matched'
            or verification.get('document_checksum') != CHECKSUM
            or semantic.get('status') != 'supported'
            or semantic.get('document_checksum') != CHECKSUM
            or applicability.get('status') != 'conditions_matched'
            or evidence.get('public_source_status') != 'available'
            or not any(s.get('available') is True
                       and s.get('document_id') == evidence.get('document_id')
                       and s.get('document_checksum') == CHECKSUM
                       and s.get('source_url') == SOURCE_URL for s in states)):
            continue
        anchors.append(adoption)
    if not anchors:
        return []
    pages = reviewed_pages(original)
    if len(pages) != 2 or normalize(ANCHOR_QUOTE) not in pages[1]:
        return []
    result = []
    for reviewed in REVIEWED:
        if normalize(reviewed['source_quote']) not in pages[reviewed['source_page'] - 1]:
            continue
        result.append({
            **reviewed, 'version': CONTEXT_VERSION,
            'document_id': evidence['document_id'], 'document_checksum': CHECKSUM,
            'source_url': SOURCE_URL, 'source_id': source_id,
            'vehicle_source_id': anchors[0]['vehicle_source_id'],
            'anchor_rule_key': anchors[0].get('rule_key'),
            'review_method': 'edition_specific_source_page_and_table_scope_review',
            'verification': 'original_checksum_and_literal_page_quote_matched',
            'applicability': 'same_scope_as_adopted_inspection_anchor',
            'calculation_permitted': False,
            'observed_vehicle_failure': False,
            'risk_score_calculation_permitted': False,
            'usage_note': '対象車両の状態・履歴と照合する知識。未記録を未実施・異常に変換しない。'
        })
    return result
