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
            '/', '/notifications', '/pointouts', '/pointouts/new',
            '/vehicle/checklists', '/safety/checklists', '/master/drivers', '/master/offices',
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
                response = self.client.get(path, follow_redirects=True)
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:300])
                html = response.get_data(as_text=True)
                self.assertIn('data-responsive-shell', html)
                self.assertEqual(html.count('css/responsive_layout.css'), 1)
                self.assertEqual(html.count('js/responsive_layout.js'), 1)
                self.assertLess(html.index('css/responsive_layout.css'), html.index('</head>'))
                self.assertLess(html.index('js/shell_bootstrap.js'), html.index('class="app-layout"'))
                for asset in ('vehicle_karte_header.css', 'vehicle_karte_overview.css', 'vehicle_karte_analysis.css', 'vehicle_data_import.css', 'import_flow.css'):
                    if 'css/' + asset in html:
                        self.assertEqual(html.count('css/' + asset), 1)
                        self.assertLess(html.index('css/' + asset), html.index('</head>'))
                self.assertNotIn('user-scalable=no', html)

    def test_phone_styles_cover_observed_overflow_and_touch_controls(self):
        from pathlib import Path
        css = (Path(__file__).resolve().parents[1] / 'static/css/responsive_layout.css').read_text()
        for selector in ('.mention-rich-editor.free-answer-input:focus',
                         '.vehicle-karte-documents .km-panel-heading',
                         '.inspection-plans .ip-month-navigation .btn',
                         '.ko-chart-months', '.kp-table-scroll .kp-table'):
            self.assertIn(selector, css)
        self.assertIn('grid-template-columns:repeat(12,minmax(44px,1fr))', css)
        self.assertIn('overflow-x:clip; overflow-y:visible', css)

    def test_shared_demo_desktop_header_reserves_its_own_row(self):
        from pathlib import Path
        css = (Path(__file__).resolve().parents[1] / 'static/css/responsive_layout.css').read_text()
        section = css.split('/* Shared demo controls follow the header on desktop too.', 1)[1]
        # Scope this contract to its media block, not unrelated rules appended later.
        start = section.index('@media')
        opening = section.index('{', start)
        depth = 1
        end = opening + 1
        while end < len(section) and depth:
            depth += (section[end] == '{') - (section[end] == '}')
            end += 1
        self.assertEqual(depth, 0, 'Desktop header media block must be balanced')
        rule = section[start:end]
        self.assertIn('@media screen and (min-width:901px)', rule)
        self.assertIn('body[data-responsive-shell][data-public-demo="true"] .main-content > .top-bar', rule)
        self.assertIn('position:relative !important; top:auto !important; right:auto !important;', rule)
        self.assertIn('margin:0 0 12px !important; min-block-size:56px;', rule)
        # The new override must not replace the phone's opaque sticky header.
        self.assertNotIn('max-width', rule)
        self.assertIn('position:sticky !important; top:0 !important; z-index:900;', css)
        template = (Path(__file__).resolve().parents[1] / 'templates/base.html').read_text()
        self.assertIn("v='20261119-header-guide-1'", template)

    def test_master_tables_have_a_scroll_viewport(self):
        for path in ('/master/offices', '/master/vehicle-types', '/master/license-types',
                     '/master/delivery-places', '/master/patrol-content-types'):
            with self.subTest(path=path):
                html = self.client.get(path).get_data(as_text=True)
                self.assertIn('table-scroll responsive-table-viewport', html)


del _Workflow

