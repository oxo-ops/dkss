"""Vehicle-choice labels stay company scoped and keep an unknown type empty."""
import unittest
from flask import template_rendered
from test_workflow_regressions import WorkflowRegressionTests as _Fixture


class VehicleChoiceLabelTests(unittest.TestCase):
    setUpClass = classmethod(_Fixture.setUpClass.__func__)
    tearDownClass = classmethod(_Fixture.tearDownClass.__func__)
    setUp = _Fixture.setUp
    tearDown = _Fixture.tearDown

    def choices(self):
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, self.m.app):
            response = self.client.get('/vehicle/karte/' + str(self.vehicle.id))
        self.assertEqual(response.status_code, 200)
        return {row['id']: row for row in contexts[-1]['karte_vehicle_choices']}

    def test_type_uses_vehicle_type_then_body_type_without_other_company(self):
        self.vehicle.type = '大型'
        self.vehicle.body_type = 'ウイング'
        fallback = self.m.Vehicle(company_code='TEST', chassis_number='FALLBACK', body_type='トレーラー')
        foreign = self.m.Vehicle(company_code='OTHER', chassis_number='FOREIGN', type='他社専用')
        self.m.db.session.add_all([fallback, foreign])
        self.m.db.session.commit()
        choices = self.choices()
        self.assertEqual(choices[self.vehicle.id]['type'], '大型')
        self.assertEqual(choices[fallback.id]['type'], 'トレーラー')
        self.assertNotIn(foreign.id, choices)

    def test_unknown_type_remains_empty(self):
        self.assertEqual(self.choices()[self.vehicle.id]['type'], '')


del _Fixture
