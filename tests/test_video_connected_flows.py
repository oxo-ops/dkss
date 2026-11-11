"""Connected video acceptance on normal Flask routes and disposable SQLite.

Only account/master fixtures, document classification/OCR and saved AI wording are
synthetic. HTTP writes, source binding, notification ownership, priority projection,
plan actuals, cost readers and analysis input builders are real. No live delivery,
AI, production DB, PostgreSQL concurrency or browser rendering is asserted here.
The existing fixtures disable CSRF, rate limiting and external delivery.
"""
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
from unittest.mock import patch
import json
import unittest

import test_q02_daily_inspection_flow as daily
import test_priority_stage2_workflow as priority
import test_q07_invoice_reimports as invoices
from test_domain_consistency import today
from test_dashboard_saved_proposals import Document


class ConnectedInspectionFlowTests(unittest.TestCase):
    setUpClass = classmethod(daily.Q02DailyInspectionFlowTests.setUpClass.__func__)
    tearDownClass = classmethod(daily.Q02DailyInspectionFlowTests.tearDownClass.__func__)
    setUp = daily.Q02DailyInspectionFlowTests.setUp
    tearDown = daily.Q02DailyInspectionFlowTests.tearDown
    login = daily.Q02DailyInspectionFlowTests.login
    request = daily.Q02DailyInspectionFlowTests.request
    save = daily.Q02DailyInspectionFlowTests.save
    complete = daily.Q02DailyInspectionFlowTests.complete
    state = daily.Q02DailyInspectionFlowTests.state
    decision_data = daily.Q02DailyInspectionFlowTests.decision_data
    decide = daily.Q02DailyInspectionFlowTests.decide
    snapshot = daily.Q02DailyInspectionFlowTests.snapshot
    assert_integrity = daily.Q02DailyInspectionFlowTests.assert_integrity
    begin_priority = priority.PriorityStage2WorkflowTests.begin_priority
    repair_priority = priority.PriorityStage2WorkflowTests.repair_priority
    _generate = priority.PriorityStage2WorkflowTests.generate

    def generate(self, kind='inspection_defect', label='低'):
        bundle, saved = self._generate(kind, label)
        # Real projection must keep saved identities and consistently sort a mix
        # of computed and legacy proposals across all three normal surfaces.
        bundle['analysis']['recommendations'].extend([
            dict(priority='低', category='整備・点検', target='保存済み別提案', title='通常記録の確認', action='記録を確認'),
            dict(priority='高', category='整備・点検', target='保存済み高提案', title='別件の確認', action='担当者へ確認')])
        saved.result_json = json.dumps(bundle, ensure_ascii=False)
        self.db.session.commit()
        return bundle, saved

    def configure_dashboard(self):
        m = self.models
        user = m.User.query.filter_by(company_code='A', username='admin').one()
        user.office = self.vehicle.office = '連続試験営業所'
        self.db.session.add(m.Office(company_code='A', name=user.office))
        self.db.session.add(m.Driver(company_code='A', employee_id='admin', name='Test admin',
                                    office=user.office, vehicles_json=json.dumps([str(self.vehicle.id)])))
        self.db.session.add(m.PatrolResult(company_code='A', office=user.office,
            target_type='delivery_place', delivery_place='架空納入先', content='動画連続受入の安全確認',
            category='指摘', date=self.day.isoformat(), countermeasure='対策を確認', approval_status='承認待ち'))
        self.db.session.commit()

    def current_analysis(self):
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/analysis/result')
        self.assertEqual(response.status_code, 200)
        return response.json['analysis']

    maxDiff = None

    def three_views(self, score, bundle, saved):
        """Real projection/cache, shared API and SSR dashboard, not frozen input."""
        self.login('admin')
        before = self.snapshot()
        analysis = self.current_analysis()
        item = analysis['recommendations'][0]
        self.assertEqual(item['priority_assessment']['effective_score'], score)
        self.assertEqual(item['priority_assessment']['label'], '高' if score == 60 else '中')
        original = saved.result_json
        from dkss_app.dashboard import get_dashboard_vehicle_attention
        with self.app.test_request_context('/'):
            group = get_dashboard_vehicle_attention('A', self.vehicle.office, [self.vehicle.id])['mine']
        self.assertEqual([x['proposal_id'] for x in group['items']], analysis['priority_order'])
        expected = {x['proposal_id']: x for x in analysis['recommendations']}
        for x in group['items']:
            # Dashboard deliberately adds a conservative freshness note; identity,
            # score, axes and registered evidence must still be identical.
            for key in ('label', 'effective_score', 'base_score', 'factors', 'source_ids',
                        'proposal_revision', 'subject_label', 'operation_decision'):
                self.assertEqual(x['priority_assessment'].get(key), expected[x['proposal_id']]['priority_assessment'].get(key))
        dashboard = self.client.get('/')
        self.assertEqual(dashboard.status_code, 200)
        root = Document(dashboard.get_data(as_text=True)).root
        panel = root.find(cls='dashboard-attention-panel')[0]
        rows = [r for body in panel.find(tag='tbody') for r in body.find(tag='tr')]
        self.assertEqual(len(rows), len(group['items']))
        for row, x in zip(rows, group['items']):
            self.assertTrue(any(a.attrs.get('href', '').endswith('#proposal=' + x['proposal_id']) for a in row.find(tag='a')))
            if x['priority_assessment']['effective_score'] is not None:
                self.assertIn(str(x['priority_assessment']['effective_score']) + '点', row.text)
        self.assertIn('dashboard_safety_attention.css', dashboard.get_data(as_text=True))
        self.assertIn('動画連続受入の安全確認', root.find(cls='dashboard-safety-attention')[0].text)
        for suffix in ('', '/analysis'):
            response = self.client.get(f'/vehicle/karte/{self.vehicle.id}{suffix}')
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn(f'/vehicle/karte/{self.vehicle.id}/analysis/result', html)
            self.assertIn('vehicle_priority_presentation.js', html)
            if suffix:
                self.assertIn('vehicle_comparison_panels.css', html)
                self.assertIn('同型式車との比較', html)
                self.assertIn('部品の交換実績', html)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(saved.result_json, original)
        return item

    def test_inspection_notification_human_stop_and_recheck_keep_one_vehicle(self):
        self.begin_priority()
        self.configure_dashboard()
        self.assertEqual(self.state()['status'], '未判定')
        notes = self.models.Notification.query.filter_by(company_code='A', target_username='admin').all()
        self.assertEqual(len(notes), 1)
        note = notes[0]
        self.assertIn(str(self.row.id), note.workflow_context_json)
        # Repeated completion cannot issue another approval request.
        before = self.snapshot()
        proof = daily.Q02DailyInspectionFlowTests.selection_proof(self)
        replay = self.client.post(f'/vehicle/checklists/{self.checklist.id}/complete', data={
            **self.form, 'approval_notify_users_0': 'admin', **proof})
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(self.snapshot(), before)
        self.login('admin')
        recent = self.client.get('/api/notifications/recent').json
        self.assertIn(note.id, [x['id'] for x in recent['notifications']])
        self.assertEqual(self.client.get(f'/notifications/{note.id}?panel=1').status_code, 200)
        # Identically named admin in another company cannot see notification or vehicle.
        self.login('admin', 'B')
        self.assertEqual(self.client.get(f'/notifications/{note.id}?panel=1').status_code, 404)
        self.assertEqual(self.client.get(f'/vehicle/karte/{self.vehicle.id}').status_code, 404)
        self.assertNotIn(note.id, [x['id'] for x in self.client.get('/api/notifications/recent').json['notifications']])
        self.decide('運行不可')
        bundle, saved = self.generate('registered_operation_instruction')
        item = self.three_views(60, bundle, saved)
        self.assertEqual(item['priority_assessment']['instruction_details']['scope'], 'whole_vehicle')
        self.assertEqual([x['points'] for x in item['priority_assessment']['factors']], [None, None, None])
        judgment = self.row.operation_judgment_json
        self.current_analysis()
        self.assertEqual(self.row.operation_judgment_json, judgment)
        # A real repair changes the current evidence. It does not clear the human stop.
        self.repair_priority()
        repair = self.models.VehicleMaintenanceRecord.query.one()
        link = self.models.VehicleMaintenanceInspectionLink.query.one()
        self.assertEqual((link.vehicle_record_id, link.inspection_result_id, link.maintenance_record_id),
                         (self.vehicle.id, self.row.id, repair.id))
        stale = self.current_analysis()['recommendations'][0]
        self.assertEqual(stale['priority'], '高')
        self.assertIsNone(stale['priority_assessment']['effective_score'])
        response = self.client.post(f'/vehicle/karte/{self.vehicle.id}/analysis/feedback', json={
            'proposal_id': item['proposal_id'], 'proposal_revision': item['proposal_revision'],
            'status': 'accepted', 'comment': '古い提案へ送らない'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.models.VehicleAnalysisFeedback.query.count(), 0)
        self.finish_recheck()
        self.assertEqual(self.models.VehicleMaintenanceRecord.query.count(), 1)
        self.assertEqual(self.state()['defects'][0]['status'], '解消')
        self.assertEqual(self.state()['status'], '未判定')
        self.decide('運行可')
        self.assert_integrity()

    def finish_recheck(self):
        self.login('checker')
        response = self.client.post(f'/vehicle/checklist-results/{self.row.id}/defects/1/repair', data={
            'judgment_version': self.state()['version'], 'repair_status': '再確認待ち',
            'repair_performed_date': self.day.isoformat(), 'repair_note': '整備後の再確認',
            'recheck_result': '異常なし'})
        self.assertEqual(response.status_code, 302)

    def test_normal_50_keeps_shared_order_with_dashboard_safety_and_comparison_panels(self):
        self.begin_priority(); self.configure_dashboard(); self.decide('運行可')
        bundle, saved = self.generate()
        item = self.three_views(50, bundle, saved)
        self.assertEqual([x['points'] for x in item['priority_assessment']['factors']], [40, None, 10])
        self.assertEqual(self.state()['status'], '運行可')

    def test_registered_recheck_waiting_25_is_not_an_automatic_operation_decision(self):
        self.begin_priority(); self.configure_dashboard(); self.decide('運行可'); self.repair_priority()
        bundle, saved = self.generate()
        item = self.three_views(25, bundle, saved)
        assessment = item['priority_assessment']
        self.assertEqual(assessment['base_score'], 0)
        self.assertEqual([x['points'] for x in assessment['factors']], [None, None, None])
        self.assertTrue(any('登録上' in x for x in assessment['missing_conditions']))
        self.assertEqual(self.state()['status'], '未判定')
        self.assertEqual(self.state()['defects'][0]['status'], '再確認待ち')
        self.finish_recheck()
        self.assertEqual(self.state()['status'], '未判定')
        self.assertIsNone(self.current_analysis()['recommendations'][0]['priority_assessment']['effective_score'])
        self.decide('運行可')
        self.assert_integrity()


class ConnectedInvoiceFlowTests(unittest.TestCase):
    setUpClass = classmethod(invoices.InvoiceReimportTests.setUpClass.__func__)
    tearDownClass = classmethod(invoices.InvoiceReimportTests.tearDownClass.__func__)
    setUp = invoices.InvoiceReimportTests.setUp
    tearDown = invoices.InvoiceReimportTests.tearDown
    source = invoices.InvoiceReimportTests.source
    upload = invoices.InvoiceReimportTests.upload
    worker = invoices.InvoiceReimportTests.worker
    draft = invoices.InvoiceReimportTests.draft
    form = invoices.InvoiceReimportTests.form
    confirm = invoices.InvoiceReimportTests.confirm
    additional = invoices.InvoiceReimportTests.additional
    review = invoices.InvoiceReimportTests.review
    edit = invoices.InvoiceReimportTests.edit
    edit_form = invoices.InvoiceReimportTests.edit_form
    assert_source = invoices.InvoiceReimportTests.assert_source

    def extract(self, source, amount='100'):
        result = invoices.InvoiceReimportTests.extract(self, source, amount)
        import maintenance_invoice_ai as ai
        part = {key: None for key in ai.line_properties}
        part.update(category='部品', description='タイヤ', quantity='2', parts_amount=amount,
                    source_page=1, replacement_action='replace', replacement_part_name='タイヤ',
                    replacement_category='消耗品')
        result['records'][0].update(content='タイヤ交換', mileage='10000', line_items=[part])
        return result

    def actuals(self):
        response = self.client.get('/api/vehicle/inspection-plans', query_string={
            'scope': 'company', 'year': today().year, 'month': today().strftime('%Y-%m')})
        self.assertEqual(response.status_code, 200)
        return response.json['invoice_actuals']

    def assert_connected(self, row, amount, source_count=1):
        m = self.m
        m.db.session.refresh(row)
        self.assertEqual(row.display_status, '実施済み')
        self.assertEqual(m.VehicleMaintenanceRecord.query.count(), 1)
        self.assertEqual(row.total_cost, Decimal(str(amount)))
        actuals = self.actuals()
        self.assertEqual(len(actuals), 1)
        self.assertEqual(actuals[0]['maintenance_record_id'], row.id)
        self.assertIn(today().strftime('%Y/%m/%d'), actuals[0]['summary'])
        self.assertIn('実施', actuals[0]['summary'])
        self.assertEqual(len(actuals[0]['sources']), source_count)
        for source in actuals[0]['sources']:
            self.assertEqual(self.client.get(source['url']).status_code, 200)
        for path, expected in (('history', row.content), ('maintenance', row.content),
                               (f'costs?year={today().year}', f'{amount:,}'), ('parts', 'タイヤ')):
            response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/{path}')
            self.assertEqual(response.status_code, 200)
            self.assertIn(expected, response.get_data(as_text=True))
        with m.app.test_request_context('/'):
            payload, sources = m.get_vehicle_karte_analysis_job_data(self.vehicle)
        record = next(x for x in payload['records'] if x['source_id'] == f'maintenance:{row.id}')
        self.assertEqual(Decimal(str(record['total_cost'])), Decimal(str(amount)))
        self.assertIn(f'maintenance:{row.id}', sources)
        part = m.VehiclePartReplacement.query.one()
        self.assertEqual(part.maintenance_record_id, row.id)
        self.assertIn(f'part:{part.id}', sources)
        analysis_page = self.client.get(f'/vehicle/karte/{self.vehicle.id}/analysis')
        self.assertEqual(analysis_page.status_code, 200)
        self.assertIn(f'data-part-source="part:{part.id}"', analysis_page.get_data(as_text=True))
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 0)
        self.assertTrue(all(p.status == 'planned' for p in m.VehicleInspectionPlan.query.all()))
        self.assertEqual(m.inspection_plans.Execution.query.count(), 0)

    def test_completed_manual_work_receives_invoice_without_second_completion(self):
        response = self.client.post(f'/vehicle/karte/{self.vehicle.id}/maintenance/new', data={
            'entry_date': today().isoformat(), 'completion_date': today().isoformat(),
            'content': '先に記録したタイヤ交換', 'status': '完了', 'maintenance_action': 'complete'})
        self.assertEqual(response.status_code, 302)
        row = self.m.VehicleMaintenanceRecord.query.one()
        record_id = row.id
        self.assertEqual(row.status, '完了')
        source = self.source()
        receipt = self.upload(source)
        self.assertEqual(receipt.status_code, 202)
        self.worker('33000')
        draft = self.draft(receipt.json)
        self.assertEqual(self.confirm(draft, row).id, record_id)
        self.assert_connected(row, 33000)
        self.assert_source(draft, source)
        self.assertEqual(self.upload(source, 'resent-late-invoice.pdf').status_code, 409)
        self.assert_connected(row, 33000)

    def test_corrected_late_invoice_reaches_rendered_comparison_and_generation_transport(self):
        """K61/K63: real displayed figures, real generator, only HTTP AI transport fake."""
        from flask import template_rendered
        import vehicle_karte_analysis_ai as generator
        m = self.m
        # A completed past month avoids future dates and cross-month numerator /
        # denominator mismatches while preserving the application's definitions.
        service_day = (today().replace(day=1) - timedelta(days=1)).replace(day=1)
        operation_day = service_day + timedelta(days=1)
        self.vehicle.model_code = 'VIDEO-COMPARISON'
        self.vehicle.first_registration_date = '2021-06'
        self.vehicle.deleted = False
        m.db.session.add(m.VehicleOperationRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            report_number='CONNECTED-OWN', operation_date=operation_day.isoformat(),
            arrival_at=operation_day.isoformat() + 'T18:00:00+09:00', distance=1000, arrival_meter=10250))
        peers = []
        for index, (cost, distance) in enumerate(((0, 100), (4000, 400), (None, None))):
            peer = m.Vehicle(company_code='TEST', chassis_number=f'CONNECTED-PEER-{index}',
                model_code=self.vehicle.model_code, first_registration_date='2021-02', deleted=False)
            m.db.session.add(peer); m.db.session.flush(); peers.append(peer)
            if distance is not None:
                m.db.session.add(m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=peer.id,
                    entry_date=service_day.isoformat(), status='完了', total_cost=cost))
                m.db.session.add(m.VehicleOperationRecord(company_code='TEST', vehicle_record_id=peer.id,
                    report_number=f'CONNECTED-PEER-{index}', operation_date=operation_day.isoformat(),
                    distance=distance, arrival_meter=10000))
        m.db.session.commit()

        def confirmed(amount, target=None):
            receipt = self.upload(self.source())
            self.assertEqual(receipt.status_code, 202)
            self.worker(amount)
            draft = self.draft(receipt.json)
            key = draft.id + '_0'
            form = self.form(draft)
            form.update({'date_' + key: service_day.isoformat(),
                         'completion_date_' + key: service_day.isoformat(), 'mileage_' + key: '10000',
                         'content_' + key: 'タイヤ交換'})
            if target is not None:
                choices = self.client.get(f'/vehicle/document-import/{draft.batch_id}/{draft.id}/0/maintenance-candidates',
                    query_string={'vehicle_id': self.vehicle.id, 'record_date': service_day.isoformat()}).json['candidates']
                form['service_match_' + key] = next(x['token'] for x in choices
                    if x['kind'] == 'maintenance' and x['record_id'] == target.id)
            response = self.client.post('/vehicle/data-import/' + draft.batch_id + '/confirm', data=form)
            self.assertEqual(response.status_code, 302)
            return draft

        original = confirmed('163900')
        row = m.VehicleMaintenanceRecord.query.filter_by(vehicle_record_id=self.vehicle.id).one()
        part = m.VehiclePartReplacement.query.filter_by(vehicle_record_id=self.vehicle.id).one()
        self.assertEqual((row.completion_date, part.replacement_date, part.mileage),
                         (service_day.isoformat(), service_day.isoformat(), 10000))
        url = f'/vehicle/karte/{self.vehicle.id}/analysis'

        def rendered(amount):
            captured = []
            def receive(sender, template, context, **extra):
                if template.name == 'vehicle_karte_analysis.html': captured.append(context)
            template_rendered.connect(receive, m.app)
            try:
                response = self.client.get(url, query_string={'start_date': service_day.isoformat(),
                    'end_date': operation_day.isoformat(), 'peer_registration': 'same_year'})
            finally:
                template_rendered.disconnect(receive, m.app)
            self.assertEqual(response.status_code, 200)
            ctx = captured[0]
            # Assertions cover both the real context and the corresponding HTML,
            # not an independently seeded result or a monkeypatched comparison.
            self.assertEqual(ctx['analysis_summary']['total_cost'], Decimal(amount))
            self.assertEqual(ctx['analysis_summary']['distance'], Decimal('1000'))
            rates = ctx['analysis_cost_comparison']
            self.assertEqual(rates['numerator'], Decimal(amount))
            self.assertEqual(rates['denominator'], Decimal('1000'))
            self.assertEqual([x['value'] for x in rates['rows']], [Decimal(amount) / 1000, Decimal('5')])
            self.assertEqual(rates['sample_count'], 2)  # Known zero included; missing excluded.
            self.assertEqual(ctx['analysis_comparison']['vehicle_count'], 3)
            self.assertEqual(ctx['analysis_comparison']['comparison_scope']['cohort_vehicle_ids'], [p.id for p in peers])
            entry, = ctx['analysis_part_history']
            self.assertEqual((entry['source_id'], entry['replacement_date'], entry['mileage'], entry['distance_since']),
                             (f'part:{part.id}', service_day.isoformat(), 10000, 250))
            self.assertIn(f'/maintenance/{row.id}', entry['url'])
            root = Document(response.get_data(as_text=True)).root
            self.assertIn(f'{amount:,}', root.find(cls='ka10-cost')[0].text)
            rate_rows = {e.attrs['data-rate']: e for e in root.find(cls='ka5-rate-row')}
            self.assertIn(f'{Decimal(amount) / 1000:,.2f}', rate_rows['current'].text)
            self.assertIn('5.00', rate_rows['average'].text)
            scope_text = ' '.join(root.find(cls='ka5-peer-panel')[0].text.split())
            self.assertIn('比較対象 3台', scope_text)
            self.assertIn('円/km算出可能 2台', scope_text)
            part_row = next(e for e in root.find(tag='tr') if e.attrs.get('data-part-source') == f'part:{part.id}')
            visible = ' '.join(part_row.text.split())
            for value in ('タイヤ', service_day.isoformat(), '250 km', '10,000 km'):
                self.assertIn(value, visible)
            self.assertEqual(m.VehicleMaintenanceRecord.query.filter_by(vehicle_record_id=self.vehicle.id).count(), 1)
            self.assertEqual(m.VehiclePartReplacement.query.filter_by(vehicle_record_id=self.vehicle.id).count(), 1)

        rendered(163900)
        # Prime the real read cache before changes; no frozen projection is used.
        self.assertEqual(self.client.get(url + '/result').status_code, 200)
        self.assertEqual(self.edit(row, content='タイヤ交換（読取訂正）', total_cost='160000').status_code, 302)
        rendered(160000)
        late = confirmed('3000', row)
        document = m.VehicleMaintenanceDocument.query.filter_by(source_draft_id=late.id).one()
        self.assertEqual(document.financial_status, 'pending')
        rendered(160000)  # Unreviewed later invoice must not alter displayed money.
        self.assertEqual(self.review(document).status_code, 302)
        rendered(163000)

        # The registered analysis URL is GET-only. Exercise its actual scheduled
        # queue/job service rather than inventing a manual POST generation route.
        with m.app.test_request_context('/'):
            payload, sources = m.get_vehicle_karte_analysis_job_data(self.vehicle)
            state = m.queue_vehicle_karte_analysis(self.vehicle, payload)
        state.next_analysis_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        m.db.session.commit()
        sent = []
        def fake_response(request, **kwargs):
            body = json.loads(request.data)
            wire = generator.expand_vehicle_karte_analysis_wire_payload(json.loads(body['input']))
            sent.append(wire)
            invoice = next(x for x in wire['records'] if x['source_id'] == f'maintenance:{row.id}')
            self.assertEqual(Decimal(str(invoice['total_cost'])), Decimal('163000'))
            self.assertEqual(invoice['content'], 'タイヤ交換（読取訂正）')
            replacement = next(x for x in wire['records'] if x['source_id'] == f'part:{part.id}')
            self.assertEqual(replacement['date'], service_day.isoformat())
            proof = replacement['replacement_document_evidence']
            self.assertEqual(proof['status'], 'verified_saved_source_line')
            self.assertEqual(proof['document_source']['sha256'], original.source_sha256)
            self.assertEqual(proof['document_source']['draft_id'], original.id)
            self.assertEqual(wire['comparison']['vehicle_count'], 3)
            # Empty generated advice is intentional: no seeded proposal can mask
            # missing inputs, fabricate a score, or claim actual model quality.
            output = {'overview': '合成応答。入力接続と保存だけの検証', 'recommendations': []}
            return BytesIO(json.dumps({'status': 'completed', 'output': [{'content': [
                {'type': 'output_text', 'text': json.dumps(output)}]}]}).encode())
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-local-test-only'}), \
                patch.object(generator.urllib.request, 'urlopen', side_effect=fake_response):
            self.assertTrue(m.run_vehicle_karte_analysis_job(state.id))
        self.assertEqual(len(sent), 1)
        m.db.session.refresh(state)
        self.assertEqual(state.status, 'completed')
        bundle = json.loads(state.result_json)
        self.assertEqual(bundle['analysis_method'], 'ai')
        self.assertEqual(bundle['analysis']['recommendations'], [])
        self.assertEqual(bundle['fingerprints'], payload['_fingerprints'])
        self.assertEqual(bundle['sources'], json.loads(json.dumps(sources, ensure_ascii=False, default=str)))
        saved_proof = bundle['sources'][f'part:{part.id}']['snapshot']['replacement_document_evidence']
        self.assertEqual(saved_proof['document_source']['sha256'], original.source_sha256)
        result = self.client.get(url + '/result')
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json['is_current'])
        self.assertEqual(result.json['sources'][f'part:{part.id}']['snapshot']['replacement_document_evidence'], saved_proof)
        self.assertEqual(self.client.get('/vehicle/data-import/files/' + original.id).data, original.source_file)

    def test_invoice_confirm_correct_resend_and_late_cost_stay_one_actual(self):
        m = self.m
        for kind in ('3month', 'vehicle_inspection'):
            m.db.session.add(m.VehicleInspectionPlan(company_code='TEST', vehicle_record_id=self.vehicle.id,
                kind=kind, planned_month=today().strftime('%Y-%m'), period_key=today().strftime('%Y-%m'),
                status='planned', source='manual', version=1))
        m.db.session.commit()
        source = self.source()
        receipt = self.upload(source)
        self.assertEqual(receipt.status_code, 202)
        self.worker('163900')
        draft = self.draft(receipt.json)
        row = self.confirm(draft)
        self.assertEqual(row.status, '完了')  # No second maintenance-complete action.
        self.assert_connected(row, 163900)
        self.assertEqual(self.client.post('/vehicle/data-import/' + draft.batch_id + '/confirm',
                                         data=self.form(draft)).status_code, 409)
        self.assertEqual(self.upload(source, 'resent.pdf').status_code, 409)
        self.assertEqual(self.edit(row, content='タイヤ交換（読取訂正）', total_cost='160000').status_code, 302)
        self.assert_connected(row, 160000)
        self.assert_source(draft, source)
        # A later separate cost document is explicitly matched to the same work.
        doc, late = self.additional(row, '3000')
        self.assertEqual(doc.financial_status, 'pending')
        self.assert_connected(row, 160000)
        self.assertEqual(self.review(doc).status_code, 302)
        self.assert_connected(row, 163000, source_count=2)
        self.assertEqual(self.review(doc).status_code, 400)
        self.assert_connected(row, 163000, source_count=2)
        self.assert_source(draft, source)


if __name__ == '__main__':
    unittest.main()
