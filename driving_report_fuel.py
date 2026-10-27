"""Reconcile explicitly paired fuel readings without borrowing or converting units."""
import unicodedata
from driving_report_data import decimal, payload


def fuel_reading(rows):
    readings=[]
    for row in rows:
        data=payload(row)
        raw=data.get('fuel_consumption')
        if raw is None or not str(raw).strip():
            continue
        amount=decimal(unicodedata.normalize('NFKC',str(raw)).strip())
        if amount is None or amount<=0:
            return None,'消費燃料が0・負数・数値未確定のため、燃費は算出していません。原本を確認してください。'
        unit=unicodedata.normalize('NFKC',str(data.get('fuel_unit') or '')).strip().casefold()
        if unit not in {'l','リットル'}:
            return None,'消費燃料と同じ日報でL単位を確認できないため、燃費は算出していません。原本の量と単位を確認してください。'
        readings.append({'amount':amount,'source':data.get('source_system') or '',
                         'version':data.get('definition_version') or '',
                         'scope':data.get('report_scope') or 'trip'})
    if not readings:
        return None,''
    if len({item['amount'] for item in readings})>1:
        return None,'同じ運行の日報で消費燃料の値が不一致です。燃費への採用を保留しています。'
    if len({(item['source'],item['version'],item['scope']) for item in readings})>1:
        return None,'同じ運行の日報で消費燃料の提供元・設定版・集計粒度が一致しません。燃費への採用を保留しています。'
    return readings[0],''
