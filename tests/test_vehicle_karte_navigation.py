"""Sidebar selection follows the resolved Karte page, including legacy aliases."""
from html.parser import HTMLParser
import unittest
import test_workflow_regressions as fixture


class Sidebar(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.groups = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        if tag == 'a' and 'menu-item' in classes:
            self.links.append(attrs)
        if tag == 'div' and 'sidebar-group' in classes:
            self.groups.append(attrs)

    @property
    def active(self):
        return [a for a in self.links if 'active' in a.get('class', '').split()]


class KarteNavigationTests(unittest.TestCase):
    setUpClass = classmethod(fixture.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = fixture.WorkflowRegressionTests.setUp
    tearDown = fixture.WorkflowRegressionTests.tearDown

    def sidebar(self, path):
        response = self.client.get(path, follow_redirects=True)
        self.assertEqual(response.status_code, 200, path)
        return Sidebar(response.get_data(as_text=True))

    def assert_karte(self, path):
        sidebar = self.sidebar(path)
        self.assertEqual([a['href'] for a in sidebar.active], ['/vehicle/karte'])
        self.assertEqual(sidebar.active[0].get('aria-current'), 'page')
        group = next(g for g in sidebar.groups if g.get('data-menu-key') == 'vehicle')
        self.assertIn('open', group['class'].split())
        master = next(a for a in sidebar.links if a['href'] == '/master/drivers')
        self.assertNotIn('aria-current', master)

    def test_history_new_and_legacy_routes_keep_same_selection(self):
        for path in (f'/vehicle/karte/{self.vehicle.id}/history',
                     f'/master/vehicles/{self.vehicle.id}/karte/history'):
            for query in ('', '?category=maintenance&page=2&per_page=10',
                          '?category=inspection&status=完了'):
                with self.subTest(path=path, query=query):
                    self.assert_karte(path + query)

    def test_list_overview_and_existing_karte_tabs_keep_selection(self):
        for path in ('/vehicle/karte', f'/vehicle/karte/{self.vehicle.id}',
                     f'/master/vehicles/{self.vehicle.id}/karte',
                     *(f'/vehicle/karte/{self.vehicle.id}/{tab}' for tab in
                       ('inspections', 'documents', 'maintenance', 'maintenance/new',
                        'parts', 'costs', 'analysis'))):
            with self.subTest(path=path):
                self.assert_karte(path)

    def test_real_master_pages_still_select_master(self):
        for path in ('/master/drivers', '/master/vehicles'):
            with self.subTest(path=path):
                sidebar = self.sidebar(path)
                self.assertEqual([a['href'] for a in sidebar.active], ['/master/drivers'])
                self.assertEqual(sidebar.active[0].get('aria-current'), 'page')

    def test_neighbor_vehicle_and_safety_pages_not_marked_as_karte(self):
        for path in ('/vehicle/checklists', '/pointouts', '/safety/checklists'):
            with self.subTest(path=path):
                sidebar = self.sidebar(path)
                self.assertEqual([a['href'] for a in sidebar.active], [path])
                self.assertFalse(any(a.get('aria-current') == 'page' for a in sidebar.links
                                     if a['href'] in ('/vehicle/karte', '/master/drivers')))
