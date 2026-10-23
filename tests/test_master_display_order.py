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
            self.assertEqual(self.client.post('/master/' + kind + '/' + str(ids[2]) + '/delete').status_code, 302)
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

if __name__ == '__main__': unittest.main()
