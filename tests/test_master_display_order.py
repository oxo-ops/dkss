"""Real master-order routes with an isolated SQLite database."""
import json
import unittest
from flask import template_rendered
import test_workflow_regressions as workflow


class MasterDisplayOrderTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def seed(self, model):
        field = 'title' if model is self.m.Manual else 'name'
        rows = [model(company_code='TEST', **{field: name}) for name in ['Zeta', 'Alpha', 'Middle']]
        foreign = model(company_code='OTHER', **{field: 'Other company'})
        self.m.db.session.add_all(rows + [foreign]); self.m.db.session.commit()
        return [r.id for r in rows], foreign.id

    def save(self, kind, ids, previous):
        return self.client.post('/master/' + kind + '/order', json={'ids': ids, 'previous_ids': previous})

    def test_seven_masters_and_shared_choices_use_saved_order(self):
        for kind, model, helper in [
            ('offices', self.m.Office, self.m.offices_for_current_company),
            ('vehicle-types', self.m.VehicleType, self.m.vehicle_types_for_current_company),
            ('license-types', self.m.LicenseType, self.m.license_types_for_current_company),
            ('delivery-places', self.m.DeliveryPlace, self.m.delivery_places_for_current_company),
            ('checklists', self.m.Checklist, self.m.checklists_for_current_company),
            ('patrol-content-types', self.m.PatrolContentType, self.m.patrol_content_types_for_current_company),
            ('manuals', self.m.Manual, self.m.manuals_for_current_company),
        ]:
            with self.subTest(kind=kind):
                ids, foreign = self.seed(model); target = [ids[2], ids[0], ids[1]]
                result = self.save(kind, target, ids)
                self.assertEqual(result.status_code, 200, result.get_data(as_text=True))
                with self.m.app.test_request_context('/'):
                    self.m.session['company_code'] = 'TEST'
                    self.assertEqual([r['id'] for r in helper()], target)
                page = self.client.get('/master/' + kind)
                self.assertEqual(page.status_code, 200)
                text = page.get_data(as_text=True)
                self.assertLess(text.index('data-master-id="'+str(target[0])+'"'), text.index('data-master-id="'+str(target[1])+'"'))
                self.assertNotIn('Other company', text)
        self.assertEqual(self.m.MasterDisplayOrder.query.count(), 7)

    def test_rename_delete_and_new_items_preserve_relative_order(self):
        ids, _ = self.seed(self.m.Office)
        self.assertEqual(self.save('offices', ids[::-1], ids).status_code, 200)
        self.m.db.session.get(self.m.Office, ids[2]).name = 'Renamed'
        self.m.db.session.delete(self.m.db.session.get(self.m.Office, ids[1]))
        new = self.m.Office(company_code='TEST', name='New')
        self.m.db.session.add(new); self.m.db.session.commit()
        self.assertEqual([r.id for r in self.m.ordered_master_query(self.m.Office, 'TEST').all()], [ids[2], ids[0], new.id])

    def test_rejects_invalid_partial_foreign_or_stale_lists(self):
        ids, foreign = self.seed(self.m.Office)
        for bad in [None, {}, ['1'], [True], [ids[0], ids[0]], ids[:-1], ids + [foreign]]:
            self.assertIn(self.save('offices', bad, ids).status_code, [400, 409])
            self.assertEqual(self.m.MasterDisplayOrder.query.count(), 0)
        self.assertEqual(self.save('offices', ids[::-1], ids).status_code, 200)
        self.assertEqual(self.save('offices', [ids[1], ids[0], ids[2]], ids).status_code, 409)
        self.assertEqual(json.loads(self.m.MasterDisplayOrder.query.one().ordered_ids_json), ids[::-1])

    def test_regular_users_cannot_change_order_and_csrf_is_enforced(self):
        ids, _ = self.seed(self.m.Office)
        user = self.m.User.query.filter_by(company_code='TEST', username='admin').one()
        user.role = 'user'; self.m.db.session.commit()
        self.assertEqual(self.save('offices', ids[::-1], ids).status_code, 302)
        self.assertEqual(self.m.MasterDisplayOrder.query.count(), 0)
        user.role = 'admin'; self.m.db.session.commit()
        self.m.app.config['WTF_CSRF_ENABLED'] = True
        try:
            self.assertEqual(self.save('offices', ids[::-1], ids).status_code, 400)
        finally:
            self.m.app.config['WTF_CSRF_ENABLED'] = False

    def test_registration_planning_and_limited_office_search(self):
        ids, _ = self.seed(self.m.Office); self.save('offices', ids[::-1], ids)
        contexts = []
        def capture(sender, template, context, **extra): contexts.append(context)
        with template_rendered.connected_to(capture, self.m.app):
            self.client.get('/master/drivers/new')
            self.assertEqual([r['id'] for r in contexts[-1]['offices']], ids[::-1])
            self.client.get('/register?company_code=TEST')
            self.assertEqual([r.id for r in contexts[-1]['offices']], ids[::-1])
            page = self.client.get('/vehicle/inspection-plans')
            self.assertEqual(page.status_code, 200)
            self.assertEqual(contexts[-1]['master_office_order'], ['Middle','Alpha','Zeta'])
            self.assertIn('master-office-order', page.get_data(as_text=True))
        self.m.User.query.filter_by(company_code='TEST', username='admin').one().role = 'itc'
        self.m.db.session.commit()
        more = [self.m.Office(company_code='TEST', name='Extra '+str(i)) for i in range(12)]
        self.m.db.session.add_all(more); self.m.db.session.commit()
        initial = ids[::-1] + [r.id for r in more]
        self.assertEqual(self.save('offices', initial[::-1], initial).status_code, 200)
        response = self.client.get('/api/news-targets?type=office')
        self.assertEqual(response.json['results'][0]['name'], 'Extra 11')
        self.assertEqual(len(response.json['results']), 10)

    def test_filtered_checklists_keep_full_order_and_fixed_template_contents(self):
        self.client.get('/master/checklists')
        ids, _ = self.seed(self.m.Checklist)
        fixed = self.m.Checklist.query.filter_by(company_code='TEST').filter(self.m.Checklist.id.notin_(ids)).one()
        original_items = fixed.items_json
        baseline = [row.id for row in self.m.ordered_master_query(self.m.Checklist, 'TEST').all()]
        target = [ids[2], fixed.id, ids[0], ids[1]]
        self.assertEqual(self.save('checklists', target, baseline).status_code, 200)
        contexts = []
        def capture(sender, template, context, **extra): contexts.append(context)
        with template_rendered.connected_to(capture, self.m.app):
            response = self.client.get('/master/checklists?keyword=Alpha')
            self.assertEqual(response.status_code, 200)
            self.assertEqual([row['id'] for row in contexts[-1]['checklists']], [ids[1]])
            self.assertEqual(contexts[-1]['master_order_ids'], target)
        self.assertEqual(self.m.db.session.get(self.m.Checklist, fixed.id).items_json, original_items)
        self.assertEqual(self.save('checklists', [ids[1]], target).status_code, 409)

    def test_extra_master_deletion_cleans_saved_ids(self):
        for kind, model in [('manuals', self.m.Manual), ('patrol-content-types', self.m.PatrolContentType), ('checklists', self.m.Checklist)]:
            ids, _ = self.seed(model)
            self.assertEqual(self.save(kind, ids[::-1], ids).status_code, 200)
            self.assertEqual(self.client.post('/master/' + kind + '/' + str(ids[2]) + '/delete', data={'confirm_delete': '1'}).status_code, 302)
            saved = self.m.MasterDisplayOrder.query.filter_by(kind=kind).one()
            self.assertEqual(json.loads(saved.ordered_ids_json), [ids[1], ids[0]])

    def test_every_master_index_has_a_visible_navigation_entry(self):
        routes = sorted({rule.rule for rule in self.m.app.url_map.iter_rules()
                         if rule.rule.startswith('/master/')
                         and rule.endpoint.endswith('_master')
                         and 'GET' in rule.methods and '<' not in rule.rule})
        self.assertEqual(len(routes), 10)
        for path in routes:
            with self.subTest(path=path):
                page = self.client.get(path)
                if path == '/master/maintenance-knowledge':
                    self.assertEqual(page.status_code, 302)
                    self.assertEqual(page.location, '/vehicle/karte')
                    continue
                self.assertEqual(page.status_code, 200)
                text = page.get_data(as_text=True)
                import re
                nav = re.search(r'<nav class="master-unified-tabs.*?</nav>', text, re.S).group()
                self.assertEqual(sorted(re.findall(r'<a href="([^"]+)"', nav)), [p for p in routes if p != '/master/maintenance-knowledge'])
                current = re.search(r'<a href="([^"]+)"[^>]*aria-current="page"', nav).group(1)
                self.assertEqual(current, path)
                self.assertEqual(text.count('class="master-unified-heading"'), 1)

    def test_order_handle_is_after_delete_in_every_reorderable_master(self):
        for kind, model in [('offices', self.m.Office), ('vehicle-types', self.m.VehicleType),
                            ('license-types', self.m.LicenseType), ('delivery-places', self.m.DeliveryPlace)]:
            self.seed(model)
            text = self.client.get('/master/' + kind).get_data(as_text=True)
            import re
            for row in re.findall(r'<tr data-master-id=.*?</tr>', text, re.S):
                self.assertLess(row.index('class="btn-small btn-delete"'), row.index('class="master-order-handle"'))
                self.assertEqual(row.count('<circle '), 6)
                self.assertNotIn('master-order-handle', row.split('</td>', 1)[0])

    def test_deleted_highest_id_does_not_reuse_its_old_position(self):
        ids, _ = self.seed(self.m.Office)
        top = self.m.Office(company_code='TEST', name='To delete')
        self.m.db.session.add(top); self.m.db.session.commit()
        old_id = top.id
        self.assertEqual(self.save('offices', [old_id] + ids, ids + [old_id]).status_code, 200)
        self.assertEqual(self.client.post('/master/offices/' + str(old_id) + '/delete').status_code, 302)
        self.assertNotIn(old_id, json.loads(self.m.MasterDisplayOrder.query.one().ordered_ids_json))
        self.assertEqual(self.client.post('/master/offices/new', data={'name': 'New office'}).status_code, 302)
        ordered = self.m.ordered_master_query(self.m.Office, 'TEST').all()
        self.assertEqual([item.name for item in ordered], ['Zeta', 'Alpha', 'Middle', 'New office'])

    def test_revision_and_company_orders_are_independent(self):
        ids, _ = self.seed(self.m.Office)
        self.save('offices', ids[::-1], ids)
        self.assertEqual(self.save('offices', ids, ids[::-1]).status_code, 200)
        self.assertEqual(self.m.MasterDisplayOrder.query.one().version, 2)
        self.assertEqual([r.name for r in self.m.ordered_master_query(self.m.Office, 'OTHER').all()], ['Other company'])
        self.assertEqual(self.save('offices', ids, ids).status_code, 200)
        self.assertEqual(self.m.MasterDisplayOrder.query.count(), 1)

    def seed_checklist_for_deletion(self):
        m = self.m
        checklist = m.Checklist(company_code='TEST', name='Test checklist', target='安全管理', items_json='[]')
        other = m.Checklist(company_code='TEST', name='Keep', target='安全管理', items_json='[]')
        m.db.session.add_all([checklist, other]); m.db.session.flush()
        safety = m.ChecklistResult(company_code='TEST', checklist_id=checklist.id, status='承認済み', answers_json='[]')
        vehicle = m.VehicleChecklistResult(company_code='TEST', checklist_id=checklist.id, vehicle_record_id=self.vehicle.id, status='承認済み', answers_json='[]')
        keep = m.ChecklistResult(company_code='TEST', checklist_id=other.id, answers_json='[]')
        m.db.session.add_all([safety, vehicle, keep]); m.db.session.commit()
        return checklist.id, safety.id, vehicle.id, keep.id

    def test_delete_checklist_requires_explicit_confirmation(self):
        ident, _, _, _ = self.seed_checklist_for_deletion()
        self.assertEqual(self.client.post(f'/master/checklists/{ident}/delete').status_code, 400)
        self.assertEqual(self.m.ChecklistResult.query.count(), 2)
        self.assertIsNotNone(self.m.db.session.get(self.m.Checklist, ident))

    def test_delete_checklist_removes_only_its_records_events_notifications_and_links(self):
        m = self.m
        ident, sid, vid, keep = self.seed_checklist_for_deletion()
        maintenance = m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id)
        m.db.session.add(maintenance); m.db.session.flush()
        m.db.session.add(m.VehicleMaintenanceInspectionLink(company_code='TEST', vehicle_record_id=self.vehicle.id, maintenance_record_id=maintenance.id, inspection_result_id=vid, defect_no=1))
        for kind, rid in [('safety', sid), ('vehicle', vid), ('safety', keep)]:
            m.db.session.add(m.ChecklistEvent(company_code='TEST', result_type=kind, result_id=rid, event_type='approved', created_at='2026-10-23'))
            m.db.session.add(m.Notification(company_code='TEST', target_user='admin', title='Test', link='/unrelated', workflow_context_json=json.dumps({'result_type': kind, 'result_id': rid})))
        m.db.session.add(m.Notification(company_code='TEST', target_user='admin', title='Legacy', link=f'/vehicle/checklists/{ident}?year=2026'))
        m.db.session.add(m.Notification(company_code='OTHER', target_user='admin', title='Other company', workflow_context_json=json.dumps({'result_type': 'safety', 'result_id': sid})))
        m.db.session.add(m.VehicleChecklistNotifySetting(company_code='TEST', checklist_id=ident, vehicle_record_id=self.vehicle.id))
        m.db.session.add(m.MasterDisplayOrder(company_code='TEST', kind='checklists', ordered_ids_json=json.dumps([ident])))
        m.db.session.commit()
        response = self.client.post(f'/master/checklists/{ident}/delete', data={'confirm_delete': '1'})
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(m.db.session.get(m.Checklist, ident))
        self.assertEqual([row.id for row in m.ChecklistResult.query.all()], [keep])
        self.assertEqual(m.VehicleChecklistResult.query.count(), 0)
        self.assertEqual(m.ChecklistEvent.query.count(), 1)
        self.assertEqual(m.Notification.query.count(), 2)
        self.assertEqual(m.VehicleMaintenanceInspectionLink.query.count(), 0)
        self.assertEqual(m.VehicleMaintenanceRecord.query.count(), 1)
        self.assertEqual(m.VehicleChecklistNotifySetting.query.count(), 0)
        self.assertEqual(json.loads(m.MasterDisplayOrder.query.one().ordered_ids_json), [])
        self.assertEqual(m.AuditLog.query.filter_by(action='checklist_deleted').count(), 1)

    def test_delete_checklist_keeps_shared_uploads_and_removes_unshared_files(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        m = self.m
        ident, sid, _, keep = self.seed_checklist_for_deletion()
        m.db.session.get(m.ChecklistResult, sid).answers_json = json.dumps([{'files': ['shared.pdf', 'private.pdf']}])
        m.db.session.get(m.ChecklistResult, keep).answers_json = json.dumps([{'files': ['shared.pdf']}])
        m.db.session.commit()
        with tempfile.TemporaryDirectory() as folder, patch.dict(m.app.config, UPLOAD_FOLDER=folder):
            company = Path(folder) / 'TEST'; company.mkdir()
            for name in ('shared.pdf', 'private.pdf'): (company / name).write_bytes(b'test')
            response = self.client.post(f'/master/checklists/{ident}/delete', data={'confirm_delete': '1'})
            self.assertEqual(response.status_code, 302)
            self.assertTrue((company / 'shared.pdf').exists())
            self.assertFalse((company / 'private.pdf').exists())

    def test_delete_checklist_rolls_back_all_database_changes_on_failure(self):
        from unittest.mock import patch
        ident, _, _, _ = self.seed_checklist_for_deletion()
        with patch.object(self.m.db.session, 'commit', side_effect=self.m.SQLAlchemyError('forced')):
            response = self.client.post(f'/master/checklists/{ident}/delete', data={'confirm_delete': '1'})
        self.assertEqual(response.status_code, 500)
        self.assertIsNotNone(self.m.db.session.get(self.m.Checklist, ident))
        self.assertEqual(self.m.ChecklistResult.query.count(), 2)
        self.assertEqual(self.m.VehicleChecklistResult.query.count(), 1)

    def test_delete_checklist_keeps_standard_and_foreign_company_and_checks_csrf(self):
        m = self.m
        self.client.get('/master/checklists')
        standard = m.Checklist.query.filter_by(company_code='TEST', target='車両管理').one()
        self.assertEqual(self.client.post(f'/master/checklists/{standard.id}/delete', data={'confirm_delete': '1'}).status_code, 403)
        foreign = m.Checklist(company_code='OTHER', name='Foreign', items_json='[]')
        m.db.session.add(foreign); m.db.session.commit()
        self.client.post(f'/master/checklists/{foreign.id}/delete', data={'confirm_delete': '1'})
        self.assertIsNotNone(m.db.session.get(m.Checklist, foreign.id))
        ident, _, _, _ = self.seed_checklist_for_deletion()
        m.app.config['WTF_CSRF_ENABLED'] = True
        try:
            self.assertEqual(self.client.post(f'/master/checklists/{ident}/delete', data={'confirm_delete': '1'}).status_code, 400)
        finally: m.app.config['WTF_CSRF_ENABLED'] = False
        m.User.query.filter_by(company_code='TEST', username='admin').one().role = 'user'; m.db.session.commit()
        self.client.post(f'/master/checklists/{ident}/delete', data={'confirm_delete': '1'})
        self.assertIsNotNone(m.db.session.get(m.Checklist, ident))

    def test_checklist_delete_button_remains_visible_for_recorded_checklists(self):
        import re
        ident, _, _, _ = self.seed_checklist_for_deletion()
        text = self.client.get('/master/checklists').get_data(as_text=True)
        forms = re.findall(r'<form\b[^>]*action="/master/checklists/' + str(ident) + r'/delete".*?</form>', text, re.S)
        self.assertEqual(len(forms), 2)
        for form in forms:
            self.assertIn('data-confirm-message=', form)
            self.assertIn('元に戻せません', form)
            self.assertIn('name="confirm_delete" value="1"', form)
        self.assertNotIn('checklist-action-menu', text)

    def seed_navigation_checklists(self, target='安全管理'):
        m = self.m
        rows = [m.Checklist(company_code='TEST', name=name, target=target, active=True, items_json='[]', frequency_unit='day', frequency_value=1, display_type='month') for name in ['First', 'Second']]
        m.db.session.add_all(rows); m.db.session.commit()
        return rows

    def test_checklist_entry_skips_list_and_uses_master_order_then_last_opened(self):
        first, second = self.seed_navigation_checklists()
        self.assertEqual(self.client.get('/safety/checklists').location, f'/safety/checklists/{first.id}')
        self.save('checklists', [second.id, first.id], [first.id, second.id])
        self.assertEqual(self.client.get('/safety/checklists').location, f'/safety/checklists/{second.id}')
        self.assertEqual(self.client.get(f'/safety/checklists/{first.id}').status_code, 200)
        self.assertEqual(self.client.get('/safety/checklists').location, f'/safety/checklists/{first.id}')
        first.active = False; self.m.db.session.commit()
        self.assertEqual(self.client.get('/safety/checklists').location, f'/safety/checklists/{second.id}')

    def test_single_checklist_has_no_switcher_and_zero_has_clear_empty_state(self):
        text = self.client.get('/safety/checklists').get_data(as_text=True)
        self.assertIn('利用できるチェックリストがありません', text)
        self.assertIn('チェックリストを管理', text)
        first, second = self.seed_navigation_checklists()
        second.active = False; self.m.db.session.commit()
        result = self.client.get('/safety/checklists', follow_redirects=True)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.request.path, f'/safety/checklists/{first.id}')
        self.assertNotIn('<details class="checklist-result-switcher">', result.get_data(as_text=True))
        self.assertNotIn('チェックリスト一覧へ', result.get_data(as_text=True))

    def test_switcher_uses_master_order_escapes_names_and_keeps_safety_filters(self):
        from urllib.parse import urlsplit, parse_qs
        from flask import template_rendered
        first, second = self.seed_navigation_checklists()
        first.name = '<img src=x onerror=alert(1)>'; self.m.db.session.commit()
        contexts = []
        def capture(sender, template, context, **extra): contexts.append(context)
        with template_rendered.connected_to(capture, self.m.app):
            page = self.client.get(f'/safety/checklists/{first.id}?target_type=office&target_value=Tokyo&next=https://evil.invalid')
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('<img src=x', page.get_data(as_text=True))
        self.assertIn('&lt;img src=x', page.get_data(as_text=True))
        choices = contexts[-1]['checklist_navigation']
        self.assertEqual([item['id'] for item in choices], [first.id, second.id])
        self.assertEqual(parse_qs(urlsplit(choices[1]['url']).query), {'target_type': ['office'], 'target_value': ['Tokyo']})

    def test_vehicle_navigation_keeps_vehicle_and_date_and_resets_incompatible_input_day(self):
        from unittest.mock import patch
        from urllib.parse import urlsplit, parse_qs
        from flask import template_rendered
        first, second = self.seed_navigation_checklists('車両管理')
        contexts = []
        def capture(sender, template, context, **extra): contexts.append(context)
        query = f'?vehicle_record_id={self.vehicle.id}&year=2026&month=09&active_day=12'
        with patch.object(self.m, 'ensure_daily_inspection_checklist'), template_rendered.connected_to(capture, self.m.app):
            entry = self.client.get('/vehicle/checklists' + query)
            self.assertEqual(entry.status_code, 302)
            self.assertEqual(urlsplit(entry.location).path, f'/vehicle/checklists/{first.id}')
            self.assertEqual(self.client.get(f'/vehicle/checklists/{second.id}' + query).status_code, 200)
            choices = contexts[-1]['checklist_navigation']
            self.assertEqual(parse_qs(urlsplit(choices[0]['url']).query), {'vehicle_record_id': [str(self.vehicle.id)], 'year': ['2026'], 'month': ['09'], 'active_day': ['12']})
            self.assertEqual(self.client.get('/vehicle/checklists').location, f'/vehicle/checklists/{second.id}')
            first.display_type = 'year'; first.frequency_unit = 'month'; self.m.db.session.commit()
            self.client.get(f'/vehicle/checklists/{second.id}' + query)
            self.assertNotIn('active_day', parse_qs(urlsplit(contexts[-1]['checklist_navigation'][0]['url']).query))

    def test_history_link_still_opens_inactive_and_can_switch_to_active(self):
        first, second = self.seed_navigation_checklists()
        first.active = False; self.m.db.session.commit()
        page = self.client.get(f'/safety/checklists/{first.id}')
        self.assertEqual(page.status_code, 200)
        self.assertIn('無効', page.get_data(as_text=True))
        self.assertIn(f'href="/safety/checklists/{second.id}"', page.get_data(as_text=True))
        self.assertEqual(self.client.get('/safety/checklists').location, f'/safety/checklists/{second.id}')

    def test_navigation_remembered_ids_are_scoped_to_user_company_and_section(self):
        first, second = self.seed_navigation_checklists()
        self.client.get(f'/safety/checklists/{second.id}')
        with self.client.session_transaction() as session:
            session['checklist_navigation_owner'] = ['OTHER', 'another-user']
            session['checklist_last_safety'] = second.id
        self.assertEqual(self.client.get('/safety/checklists').location, f'/safety/checklists/{first.id}')
        foreign = self.m.Checklist(company_code='OTHER', name='Foreign', target='安全管理', active=True, items_json='[]')
        self.m.db.session.add(foreign); self.m.db.session.commit()
        with self.client.session_transaction() as session: session['checklist_last_safety'] = foreign.id
        self.assertEqual(self.client.get('/safety/checklists').location, f'/safety/checklists/{first.id}')
        self.assertEqual(self.client.get(f'/safety/checklists/{foreign.id}').status_code, 302)
        with self.client.session_transaction() as session: session['checklist_last_safety'] = 999999
        self.assertEqual(self.client.get('/safety/checklists').location, f'/safety/checklists/{first.id}')

    def test_safety_result_rejects_vehicle_checklist_and_vehicle_empty_has_no_loop(self):
        from unittest.mock import patch
        first, second = self.seed_navigation_checklists('車両管理')
        self.assertEqual(self.client.get(f'/safety/checklists/{first.id}').location, '/safety/checklists')
        first.active = second.active = False; self.m.db.session.commit()
        with patch.object(self.m, 'ensure_daily_inspection_checklist'):
            response = self.client.get('/vehicle/checklists', follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.request.path, '/vehicle/checklists')
            self.assertIn('利用できるチェックリストがありません', response.get_data(as_text=True))

    def test_vehicle_normal_header_has_switcher_and_no_old_list_back_link(self):
        first, second = self.seed_navigation_checklists('車両管理')
        text = self.client.get(f'/vehicle/checklists/{first.id}').get_data(as_text=True)
        self.assertIn('<details class="checklist-result-switcher">', text)
        self.assertIn(f'href="/vehicle/checklists/{second.id}"', text)
        self.assertNotIn('点検一覧に戻る', text)

    def test_entry_templates_keep_links_if_rendered_with_available_checklists(self):
        from flask import render_template
        first, second = self.seed_navigation_checklists()
        with self.m.app.test_request_context('/'):
            self.m.session['company_code'] = 'TEST'
            self.m.session['role'] = 'admin'
            rows = [self.m.checklist_to_dict(first), self.m.checklist_to_dict(second)]
            for section in ('safety', 'vehicle'):
                text = render_template(section + '_checklists.html', checklists=rows)
                self.assertIn(f'href="/{section}/checklists/{first.id}"', text)
                self.assertNotIn('利用できるチェックリストがありません', text)

if __name__ == '__main__': unittest.main()
