"""Vehicle edit navigation: real Flask requests/templates, isolated storage stubs."""
import ast
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from flask import Flask, redirect, render_template, request, session
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def controller_functions():
    source = ast.parse((ROOT / 'dkss_app/vehicle_master.py').read_text(encoding='utf-8'))
    wanted = {'_vehicle_edit_return_target', 'edit_vehicle'}
    nodes = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    if len(nodes) != 2:
        raise AssertionError('Navigation functions missing')
    return compile(ast.Module(body=nodes, type_ignores=[]), 'vehicle_master.py', 'exec')


class Fields(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name'):
            self.values[attrs['name']] = attrs.get('value', '')
        if tag == 'a':
            self.links.append(attrs.get('href'))


class VehicleEditReturnTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'navigation-test-only'
        self.app.jinja_loader = ChoiceLoader([
            DictLoader({'base.html': '{% block page_styles %}{% endblock %}{% block content %}{% endblock %}'}),
            FileSystemLoader(str(ROOT / 'templates')),
        ])
        self.app.jinja_env.globals['csrf_token'] = lambda: 'test-token'
        self.vehicle = SimpleNamespace(id=66, company_code='A',
            plate_area='Test', plate_class='100', plate_kana='a', plate_number='1234',
            chassis_number='SYNTHETIC-66', model_code='', first_registration_date='',
            manufacturer='Sample', body_type='', gross_vehicle_weight=None, max_payload=None,
            type='', office='', inspection_expiry='')
        self.query = MagicMock()
        self.query.filter_by.return_value.first.return_value = self.vehicle
        self.query.filter.return_value.first.return_value = None
        self.apply = MagicMock()
        self.db = MagicMock()
        common = SimpleNamespace(request=request, session=session, redirect=redirect,
            render_template=render_template, db=self.db, VEHICLE_MAINTENANCE_ATTRIBUTE_FIELDS=[])
        self.scope = {
            '_dkss_common': common,
            '_dkss_models': SimpleNamespace(Vehicle=SimpleNamespace(query=self.query,
                company_code=MagicMock(), chassis_number=MagicMock(), id=MagicMock())),
            '_dkss_master_readers': SimpleNamespace(offices_for_current_company=lambda: []),
            '_dkss_vehicle_readers': SimpleNamespace(vehicle_types_for_current_company=lambda: [], vehicle_number=lambda v: 'Test'),
            '_dkss_knowledge': SimpleNamespace(link_vehicle_certificate_specification_source=MagicMock()),
            '_dkss_http': SimpleNamespace(return_form_errors=lambda errors, *a: ('invalid', 400)),
            'validate_vehicle_dates': lambda *a: [],
            'validate_vehicle_text_fields': lambda *a: [],
            'validate_vehicle_master_values': lambda *a: [],
            'parse_vehicle_weights': lambda *a: ({'gross_vehicle_weight': 0, 'max_payload': 0}, []),
            'apply_vehicle_form_values': self.apply,
        }
        exec(controller_functions(), self.scope)
        self.app.add_url_rule('/master/vehicles/<int:index>/edit', 'edit_vehicle',
            self.scope['edit_vehicle'], methods=['GET', 'POST'])
        self.app.add_url_rule('/master/vehicles', 'vehicle_master', lambda: '')
        self.app.add_url_rule('/vehicle/karte/<int:vehicle_record_id>', 'vehicle_karte', lambda vehicle_record_id: '')
        self.client = self.app.test_client()
        with self.client.session_transaction() as state:
            state['company_code'] = 'A'

    def flow(self, target, expected):
        response = self.client.get('/master/vehicles/66/edit', query_string={'return_to': target})
        self.assertEqual(response.status_code, 200)
        fields = Fields(response.get_data(as_text=True))
        self.assertEqual(fields.values['return_to'], expected)
        self.assertIn(expected, fields.links)
        self.query.filter_by.assert_called_with(id=66, company_code='A')
        response = self.client.post('/master/vehicles/66/edit', data=fields.values)
        self.assertEqual(response.status_code, 200)
        confirm = Fields(response.get_data(as_text=True)).values
        self.assertEqual(confirm['return_to'], expected)
        self.apply.assert_not_called()
        response = self.client.post('/master/vehicles/66/edit', data={**confirm, 'vehicle_form_action': 'back'})
        self.assertEqual(response.status_code, 200)
        back = Fields(response.get_data(as_text=True))
        self.assertEqual(back.values['return_to'], expected)
        self.assertIn(expected, back.links)
        response = self.client.post('/master/vehicles/66/edit', data={**confirm, 'vehicle_form_action': 'save'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], expected)
        self.apply.assert_called_once()
        self.db.session.commit.assert_called_once()

    def test_karte_origin_survives_confirmation_back_and_save(self):
        self.flow('/vehicle/karte/66', '/vehicle/karte/66')

    def test_karte_tab_origin_is_preserved(self):
        self.flow('/vehicle/karte/66/history?kind=inspection', '/vehicle/karte/66/history?kind=inspection')

    def test_master_origin_preserves_search_conditions(self):
        self.flow('/master/vehicles?office=Sample&inactive=0', '/master/vehicles?office=Sample&inactive=0')

    def test_karte_list_origin_is_preserved(self):
        self.flow('/vehicle/karte?office=Sample', '/vehicle/karte?office=Sample')

    def test_direct_entry_defaults_to_master(self):
        response = self.client.get('/master/vehicles/66/edit')
        self.assertEqual(Fields(response.get_data(as_text=True)).values['return_to'], '/master/vehicles')

    def test_untrusted_destinations_are_rejected(self):
        resolve = self.scope['_vehicle_edit_return_target']
        for target in [None, '', 'https://example.com', '//example.com',
                       '/\\example.com', '/master/vehicles\r\nLocation: https://example.com',
                       '/vehicle/karte/67', '/vehicle/karte/66/delete', '/admin',
                       '/master/vehicles#fragment', 'http://[invalid',
                       '/%2f%2fexample.com', 'https://local/master/vehicles']:
            with self.subTest(target=target):
                self.assertEqual(resolve(target, 66)[0], '/master/vehicles')

    def test_forged_destination_on_save_is_revalidated(self):
        response = self.client.post('/master/vehicles/66/edit', data={
            'chassis_number': 'SYNTHETIC-66', 'vehicle_form_action': 'save',
            'return_to': '//example.com',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/master/vehicles')

    def test_missing_or_foreign_vehicle_still_returns_to_master(self):
        self.query.filter_by.return_value.first.return_value = None
        response = self.client.get('/master/vehicles/66/edit', query_string={'return_to': '/vehicle/karte/66'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/master/vehicles')
        self.apply.assert_not_called()


    def test_master_list_links_preserve_karte_origin(self):
        template = (ROOT / 'templates/vehicle_master.html').read_text(encoding='utf-8')
        links = re.findall('href="({{ url_for\\(\'edit_vehicle\'.*?)"', template)
        self.assertEqual(len(links), 2)  # Desktop and mobile both use real template links.
        for query, expected in [('', '/master/vehicles'),
                                ('?edit_origin=karte', '/vehicle/karte/66'),
                                ('?edit_origin=karte&page=2', '/vehicle/karte/66')]:
            with self.app.test_request_context('/master/vehicles' + query):
                for link in links:
                    rendered = unescape(self.app.jinja_env.from_string(link).render(vehicle={'index': 66}))
                    self.assertEqual(parse_qs(urlsplit(rendered).query)['return_to'], [expected])

    def test_karte_list_button_carries_origin(self):
        template = (ROOT / 'templates/vehicle_karte_header.html').read_text(encoding='utf-8')
        links = re.findall('href="({{ url_for\\(\'vehicle_master\'.*?)"', template)
        self.assertEqual(len(links), 1)
        with self.app.test_request_context('/vehicle/karte/66'):
            rendered = unescape(self.app.jinja_env.from_string(links[0]).render())
            self.assertEqual(parse_qs(urlsplit(rendered).query)['edit_origin'], ['karte'])


if __name__ == '__main__':
    unittest.main()
