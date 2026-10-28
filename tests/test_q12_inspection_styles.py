"""Planner CSS must block first paint on every page using its shared panel."""
from html.parser import HTMLParser
import unittest

import test_workflow_regressions as workflow


class Styles(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.planner = []
        self.panel_scripts = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "head":
            self.in_head = True
        if tag == "link" and "vehicle_inspection_plans.css" in attrs.get("href", ""):
            self.planner.append((self.in_head, attrs.get("rel")))
        if tag == "script" and "vehicle_inspection_plans.js" in attrs.get("src", ""):
            self.panel_scripts += 1

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


class InspectionStyleDeliveryTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def test_real_routes_deliver_one_blocking_stylesheet_in_head(self):
        root = f"/vehicle/karte/{self.vehicle.id}"
        for route in ["/vehicle/inspection-plans", root] + [
            root + "/" + part for part in
            ("history", "inspections", "documents", "maintenance", "parts", "costs", "analysis")
        ]:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                parser = Styles()
                parser.feed(response.get_data(as_text=True))
                self.assertEqual(parser.planner, [(True, "stylesheet")])
                self.assertEqual(parser.panel_scripts, 1)

    def test_unrelated_pages_do_not_fetch_planner_assets(self):
        for route in ("/", "/settings", "/master/vehicles"):
            with self.subTest(route=route):
                parser = Styles()
                parser.feed(self.client.get(route).get_data(as_text=True))
                self.assertEqual(parser.planner, [])
                self.assertEqual(parser.panel_scripts, 0)
