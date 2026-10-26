"""The shared responsive contract is rendered on real application routes."""
import unittest
from test_workflow_regressions import WorkflowRegressionTests as _Workflow


class ResponsiveLayoutTests(unittest.TestCase):
    setUpClass = classmethod(_Workflow.setUpClass.__func__)
    tearDownClass = classmethod(_Workflow.tearDownClass.__func__)
    setUp = _Workflow.setUp
    tearDown = _Workflow.tearDown

    def test_shared_viewport_contract_on_application_pages(self):
        pages = [
            '/', '/notifications', '/master/drivers', '/master/offices',
            '/master/vehicles', '/master/vehicle-types', '/master/license-types',
            '/master/delivery-places', '/master/checklists',
            '/master/patrol-content-types', '/vehicle/data-import',
            '/vehicle/inspection-plans?scope=company', '/safety/driving-reports',
        ]
        base = f'/vehicle/karte/{self.vehicle.id}'
        pages += [base + suffix for suffix in ('', '/history', '/inspections',
                   '/maintenance', '/parts', '/costs', '/documents', '/analysis')]
        for path in pages:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:300])
                html = response.get_data(as_text=True)
                self.assertIn('data-responsive-shell', html)
                self.assertEqual(html.count('css/responsive_layout.css'), 1)
                self.assertEqual(html.count('js/responsive_layout.js'), 1)
                self.assertGreater(html.index('css/responsive_layout.css'), html.rfind('</main>'))
                self.assertNotIn('user-scalable=no', html)

    def test_master_tables_have_a_scroll_viewport(self):
        for path in ('/master/offices', '/master/vehicle-types', '/master/license-types',
                     '/master/delivery-places', '/master/patrol-content-types'):
            with self.subTest(path=path):
                html = self.client.get(path).get_data(as_text=True)
                self.assertIn('table-scroll responsive-table-viewport', html)


del _Workflow
