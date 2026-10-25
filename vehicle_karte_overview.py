"""Read-only summaries for the vehicle's first screen. No AI calls or DB writes."""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from flask import url_for


def day(value):
    try:
        return date.fromisoformat(str(value or '')[:10].replace('/', '-'))
    except (TypeError, ValueError):
        return None


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (TypeError, ValueError, InvalidOperation):
        return None


def build_overview(g, vehicle):
    """g is the app's namespace, including existing company-scoped readers."""
    today = datetime.now(ZoneInfo('Asia/Tokyo')).date()
    code, vid = vehicle.company_code, vehicle.id
    def rows(model):
        return g[model].query.filter_by(company_code=code, vehicle_record_id=vid).all()
    maintenance, _, _ = g['filter_vehicle_maintenance_factual_history'](rows('VehicleMaintenanceRecord'))
    periodic = [r for r in rows('VehiclePeriodicInspectionRecord') if not g['periodic_inspection_synthetic_evidence'](r)]
    reference = g['build_vehicle_karte_mileage_reference'](
        maintenance, rows('VehicleOperationRecord'), today.isoformat(), periodic, include_points=True)
    history = g['get_vehicle_karte_history_entries'](code, vid)
    factual_ids = {f'maintenance:{r.id}' for r in maintenance}
    periodic_ids = {f'periodic:{r.id}' for r in periodic}
    by_maintenance = {r.id: r for r in maintenance}
    recent = []
    for entry in history:
        key = entry['key']
        if key.startswith('maintenance:') and key not in factual_ids:
            continue
        if key.startswith('periodic:') and key not in periodic_ids:
            continue
        if not day(entry['date']) or day(entry['date']) > today:
            continue
        entry = dict(entry)
        if key in factual_ids:
            record = by_maintenance[int(key.split(':')[1])]
            entry['link'] = url_for('vehicle_karte_maintenance', vehicle_record_id=vid, record_id=record.id)
        recent.append(entry)

    completed = [r for r in maintenance if (r.completion_date or r.status == '完了')
                 and day(r.completion_date or r.entry_date) and day(r.completion_date or r.entry_date) <= today]
    last = max(completed, key=lambda r: (day(r.completion_date or r.entry_date), r.id), default=None)
    def distance_since(mileage, performed):
        recorded = day(performed)
        before = number(mileage)
        current = number(reference['value'])
        if (reference['distance_usable'] and recorded and day(reference['date']) >= recorded
                and before is not None and current is not None and current >= before):
            return current - before
        return None
    last_day = day(last.completion_date or last.entry_date) if last else None
    metrics = {'last_date': last_day.isoformat() if last_day else None,
               'last_mileage': number(last.mileage) if last else None,
               'distance_since': distance_since(last.mileage, last_day) if last else None}
    # A month-only registration establishes years/months, never an invented day.
    age = ''
    first = str(vehicle.first_registration_date or '').replace('/', '-')
    try:
        year, month = int(first[:4]), int(first[5:7])
        age_months = (today.year - year) * 12 + today.month - month
        if 1 <= month <= 12 and 1900 <= year <= today.year and age_months >= 0:
            age = f'{age_months // 12}年{age_months % 12}か月'
    except (TypeError, ValueError):
        pass

    groups = g['get_vehicle_karte_parts_context'](vehicle, factual_only=True)['part_groups']
    stored = g['VehicleKarteAnalysis'].query.filter_by(company_code=code, vehicle_record_id=vid).first()
    bundle = g['safe_json_dict'](stored.result_json) if stored else {}
    analysis = bundle.get('analysis') or {}
    targets = [str(item.get('target') or '') for item in analysis.get('recommendations', [])
               if isinstance(item, dict)] if isinstance(analysis, dict) else []
    def part_order(group):
        target = any(group['part_name'] in name or name in group['part_name'] for name in targets if name)
        performed = day(group['latest'].replacement_date)
        return (not target, group['priority'] >= 99, -(performed.toordinal() if performed else 0), group['priority'], group['part_name'])
    parts = []
    for group in sorted(groups, key=part_order):
        part = group['latest']
        recorded = day(part.replacement_date)
        if recorded and recorded > today:
            continue
        # U32: a stale generated part must not yield a confident elapsed value.
        parent = by_maintenance.get(part.maintenance_record_id)
        parent_day = day(parent.completion_date or parent.entry_date) if parent else None
        compatible = not parent or ((parent.mileage is None or number(parent.mileage) == number(part.mileage))
                                     and (not parent_day or parent_day == recorded))
        parts.append({**group, 'date': recorded.isoformat() if recorded else None,
                      'mileage': number(part.mileage),
                      'distance_since': distance_since(part.mileage, recorded) if compatible else None,
                      'days_since': (today - recorded).days if recorded else None,
                      'needs_review': not compatible})
    parts = parts[:5]

    daily = []
    for record in rows('VehicleChecklistResult'):
        snapshot = g['safe_json_dict'](record.checklist_snapshot_json)
        if not any(isinstance(i, dict) and i.get('fixed_template_code') == 'daily_inspection_truck_trailer'
                   for i in snapshot.get('items', [])):
            continue
        try:
            performed = date(int(record.year), int(record.month), int(record.day))
        except (ValueError, TypeError):
            continue
        if performed <= today:
            daily.append((performed, record))
    daily.sort(key=lambda x: (x[0], x[1].id), reverse=True)
    current = [(performed, r) for performed, r in daily if performed == today]
    inspection = {'date': today.isoformat(), 'label': '本日の記録なし', 'judgment': '未判定',
                  'by': '', 'at': '', 'reason': '',
                  'link': url_for('vehicle_karte_inspections', vehicle_record_id=vid, inspection_view='daily')}
    if current:
        # Do not choose one favourable judgment when multiple records disagree.
        judgments = [g['safe_json_dict'](r.operation_judgment_json) for _, r in current]
        valid = {'運行可', '運行不可', '判断保留'}
        states = {(j.get('status') if day(j.get('judged_at')) == today else '判断日時を確認')
                  if j.get('status') in valid else '未判定' for j in judgments}
        chosen = judgments[0]
        inspection.update(label='点検完了' if all(r.status in {'承認待ち', '承認済み', '点検完了'} for _, r in current) else '点検入力中',
                          judgment=next(iter(states)) if len(states) == 1 else '記録間の判断を確認',
                          by=chosen.get('judged_by') or chosen.get('judged_by_username') or '',
                          at=str(chosen.get('judged_at') or '')[:16], reason=chosen.get('reason') or '',
                          link=url_for('vehicle_checklist_results', index=current[0][1].checklist_id,
                                       vehicle_record_id=vid, year=today.year, month=today.month, active_day=today.day))
        inspection['judgment_summary'] = ' / '.join(sorted(states)) if len(states) > 1 else ''
        inspection['has_unavailable'] = '運行不可' in states
        if inspection['judgment'] not in valid:
            inspection.update(by='', at='')
        if inspection['label'] == '点検入力中' or len(states) != 1:
            inspection.update(judgment='判断待ち' if len(states) == 1 else '記録間の判断を確認', by='', at='')
    elif daily:
        inspection['previous_date'] = daily[0][0].isoformat()

    actions = []
    steps = {'対応待ち': '整備内容を登録', '整備中': '作業状況を確認', '再確認待ち': '整備後の再確認'}
    daily_issues = g['get_vehicle_open_inspection_defects'](code, vid)
    for row in daily_issues:
        defect = row['defect']
        answer = defect.get('reported_answer') or {}
        answer = answer if isinstance(answer, dict) else {}
        repair = defect.get('repair') or {}
        repair = repair if isinstance(repair, dict) else {}
        actions.append({'key': f"daily:{row['result_id']}:{defect.get('item_no', '')}",
                        'label': answer.get('content') or '日常点検の指摘',
                        'detail': answer.get('comment') or '', 'status': defect.get('status') or '対応待ち',
                        'next': steps.get(defect.get('status'), '指摘を確認'),
                        'by': ('最終対応 ' + str(repair['performed_by'])) if repair.get('performed_by') else '担当者未設定',
                        'date': row['inspection_date'], 'link': row['link']})
    linked_maintenance = set()
    open_daily = {(row['result_id'], str(row['defect'].get('defect_no'))) for row in daily_issues}
    for link in rows('VehicleMaintenanceInspectionLink'):
        if (link.inspection_result_id, str(link.defect_no)) in open_daily:
            linked_maintenance.add(link.maintenance_record_id)
    for issue in g['periodic_followups'].summary(code, vid)['issues']:
        if issue.status in {'解消', '取消'}:
            continue
        if issue.maintenance_record_id:
            linked_maintenance.add(issue.maintenance_record_id)
        actions.append({'key': f'periodic_issue:{issue.id}', 'label': issue.description,
                        'detail': '定期点検の指摘', 'status': issue.status,
                        'next': steps.get(issue.status, '指摘を確認'), 'by': '担当者未設定',
                        'date': str(issue.created_at or '')[:10],
                        'link': url_for('vehicle_periodic_followup', vehicle_record_id=vid,
                                        record_id=issue.inspection_record_id) + f'#periodic-issue-{issue.id}'})
    for record in maintenance:
        if record.id in linked_maintenance or record.status not in {'整備中', '再確認待ち'}:
            continue
        actions.append({'key': f'maintenance:{record.id}', 'label': record.content or record.symptom or '整備・修理',
                        'detail': record.maintenance_company or '', 'status': record.status,
                        'next': steps.get(record.status, '整備状況を確認'), 'by': '担当者未設定',
                        'date': record.entry_date or record.completion_date or '日付未登録',
                        'link': url_for('vehicle_karte_maintenance', vehicle_record_id=vid, record_id=record.id)})
    for record in rows('VehiclePatrol'):
        if record.status not in {'未対応', '対応中'}:
            continue
        actions.append({'key': f'patrol:{record.id}', 'label': record.content or record.category or '車両の故障・不具合',
                        'detail': record.category or '', 'status': record.status, 'priority': record.priority,
                        'next': '対応状況を確認', 'by': record.repair_person or '担当者未設定',
                        'date': record.occurred_date or '日付未登録',
                        'link': url_for('vehicle_patrol_detail', index=record.id)})
    actions.sort(key=lambda r: (0 if r.get('priority') == '高' else 1,
                               0 if r['status'] == '再確認待ち' else 1, r['date'], r['key']))

    # Match the cost tab's rolling period: the 12 complete calendar months before this month.
    details = g['get_vehicle_maintenance_cost_details'](maintenance, today.year)
    start, end = day(details['average_start']), day(details['average_end_exclusive'])
    cost_rows = [r for r in maintenance if day(r.entry_date or r.completion_date)
                 and start <= day(r.entry_date or r.completion_date) < end]
    cost = {'total': g['get_vehicle_maintenance_cost_summary'](cost_rows)['total_cost'],
            'start': start.isoformat(), 'end': (end - timedelta(days=1)).isoformat(),
            'count': len(cost_rows), 'missing': sum(r.total_cost is None for r in cost_rows),
            'undated': details['undated_record_count'],
            'high': sorted([r for r in cost_rows if r.total_cost is not None],
                           key=lambda r: (r.total_cost, r.id), reverse=True)[:2]}

    documents = g['get_vehicle_karte_documents'](vehicle)
    g['build_vehicle_karte_documents_context'](vehicle, documents)
    business = []
    seen = set()
    for document in documents:
        if document['kind'] == 'operation_csv' or document['key'] in seen:
            continue
        seen.add(document['key'])
        doc = dict(document, related_url=None, business_date=None, date_kind='登録日')
        for source in document.get('records', []):
            if not isinstance(source, dict):
                continue
            rid = source.get('record_id')
            # A draft's record identifier is scoped and checked before linking.
            record = next((r for r in maintenance if str(r.id) == str(rid)), None) if document['document_type'] == 'maintenance' else None
            if record:
                performed = day(record.completion_date or record.entry_date)
                doc.update(related_url=url_for('vehicle_karte_maintenance', vehicle_record_id=vid, record_id=record.id),
                           related_label=record.content or '整備記録', business_date=performed.isoformat() if performed else None,
                           date_kind='整備日' if performed else '登録日')
                break
            if document['document_type'] == 'inspection':
                record = next((r for r in periodic if str(r.id) == str(rid)), None)
                if record:
                    doc.update(related_url=url_for('vehicle_karte_inspections', vehicle_record_id=vid, inspection_view={'3month': '3month', '12month': '12month', 'vehicle_inspection': 'certificate'}.get(record.inspection_type, 'all'), start_date=record.inspection_date, end_date=record.inspection_date) + f'#periodic-record-{record.id}',
                               related_label=record.content or '点検記録', business_date=record.inspection_date, date_kind='実施日',
                               kind_label={'3month': '3か月点検', '12month': '12か月点検'}.get(record.inspection_type, '定期点検'))
                    break
        business.append(doc)
    note = g['VehicleKarteNote'].query.filter_by(company_code=code, vehicle_record_id=vid).first()
    note_author = ''
    if note and note.updated_by_username:
        author = g['User'].query.filter_by(company_code=code, username=note.updated_by_username).first()
        note_author = ((author.last_name or '') + (author.first_name or '')).strip() if author else ''
        note_author = note_author or note.updated_by_username
    return {'karte_mileage_reference': reference, 'karte_mileage_points': reference['points'],
            'karte_recent_entries': recent[:5], 'karte_parts_ranking': groups[:5],
            'ko_parts': parts, 'ko_metrics': metrics, 'ko_age': age, 'ko_today': today.isoformat(),
            'ko_inspection': inspection, 'ko_actions': actions, 'ko_cost': cost,
            'karte_note': note, 'ko_note_author': note_author,
            'karte_recent_documents': business[:3], 'karte_document_count': len(documents),
            'ko_business_document_count': len(business)}
