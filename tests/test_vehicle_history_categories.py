"""History facets: real routes, isolated DB, no fabricated import history."""
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from html.parser import HTMLParser
from flask import template_rendered
import test_workflow_regressions as fixture


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.links = []; self.feed(html)
    def handle_starttag(self, tag, attrs):
        if tag == 'a': self.links.append(dict(attrs))


class HistoryCategoryTests(unittest.TestCase):
    setUpClass = classmethod(fixture.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = fixture.WorkflowRegressionTests.setUp
    tearDown = fixture.WorkflowRegressionTests.tearDown

    def row(self, key, kind='点検', date='2026-11-01', status='完了'):
        return dict(key=key, kind=kind, date=date, status=status, content=key,
                    mileage=None, cost=None, actor='', link=None, files=[])

    def get(self, query='', rows=None):
        from dkss_app import vehicle_karte
        contexts = []
        def capture(sender, template, context, **extra): contexts.append(context)
        with template_rendered.connected_to(capture, self.m.app):
            if rows is None:
                response = self.client.get(f'/master/vehicles/{self.vehicle.id}/karte/history' + query)
            else:
                with patch.object(vehicle_karte, 'get_vehicle_karte_history_entries', return_value=rows):
                    response = self.client.get(f'/master/vehicles/{self.vehicle.id}/karte/history' + query)
        return response, contexts[-1] if contexts else {}

    def counts(self, context):
        return {row['key']: row['count'] for row in context['history_categories']}

    def test_source_categories_and_unknown_are_exhaustive(self):
        from dkss_app.vehicle_karte import vehicle_history_category
        examples = {'inspection:1':'inspection', 'defect:1':'inspection',
            'periodic:1':'inspection', 'periodic-issue-event:1':'inspection',
            'inspection-plan:1':'inspection', 'inspection-execution:1':'inspection',
            'inspection-repair:1':'maintenance', 'maintenance:1':'maintenance',
            'driving-report:1':'other', 'future:1':'other'}
        for key, expected in examples.items():
            self.assertEqual(vehicle_history_category(self.row(key)), expected)
        self.assertEqual(vehicle_history_category(self.row('periodic:1', kind='突発修理')), 'maintenance')
        self.assertEqual(vehicle_history_category(dict(self.row('inspection-plan:1'), history_category='maintenance')), 'maintenance')
        self.assertEqual(vehicle_history_category(dict(self.row('inspection-plan:1'), history_category='future')), 'other')

    def test_counts_before_category_and_pagination_links_preserve_filters(self):
        rows = [self.row(f'maintenance:{i}') for i in range(25)] + [self.row('inspection:1'), self.row('driving-report:1')]
        response, ctx = self.get('?category=maintenance&page=2&per_page=10&status=完了&event_type=点検&start_date=2026-11-01&end_date=2026-11-01', rows)
        self.assertEqual(response.status_code, 200)
        self.assertIn('vehicle_karte_history.css?v=20261110-presentation-3', response.get_data(as_text=True))
        self.assertEqual(self.counts(ctx), {'':27, 'inspection':1, 'maintenance':25, 'other':1})
        self.assertEqual(ctx['history_page'].total, 25)
        self.assertEqual(len(ctx['history_page'].items), 10)
        links = Links(response.get_data(as_text=True)).links
        facet = next(link for link in links if link.get('data-category') == 'inspection')
        args = parse_qs(urlsplit(facet['href']).query)
        self.assertNotIn('page', args)
        self.assertEqual(args['status'], ['完了'])
        self.assertEqual(args['event_type'], ['点検'])
        self.assertEqual(args['end_date'], ['2026-11-01'])
        self.assertEqual(args['per_page'], ['10'])
        previous = next(link for link in links if link.get('aria-label') == '前のページ')
        self.assertEqual(parse_qs(urlsplit(previous['href']).query)['category'], ['maintenance'])
        self.assertIn('name="category" value="maintenance"', response.get_data(as_text=True))
        selected = next(link for link in links if link.get('data-category') == 'maintenance')
        self.assertEqual(selected['aria-current'], 'true')

    def test_type_status_dates_apply_to_counts_and_unknown_dates_are_not_zero(self):
        rows = [self.row('maintenance:1'), self.row('inspection:1', status='予定'),
                self.row('inspection:2', date=''), self.row('inspection:3', date='2026-10-01'),
                self.row('driving-report:1', kind='安全運転日報')]
        response, ctx = self.get('?start_date=2026-11-01&end_date=2026-11-01&status=完了&event_type=点検', rows)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.counts(ctx), {'':1, 'inspection':0, 'maintenance':1, 'other':0})
        _, ctx = self.get('?category=inspection', rows)
        self.assertEqual(ctx['history_page'].total, 3)
        self.assertEqual(ctx['history_page'].items[1]['date'], '')

    def test_empty_invalid_dates_unknown_category_and_page_clamping(self):
        for query in ('?start_date=invalid', '?start_date=2026-11-02&end_date=2026-11-01'):
            response, ctx = self.get(query, [self.row('inspection:1')])
            self.assertEqual(response.status_code, 400)
            self.assertEqual(sum(self.counts(ctx).values()), 0)
        _, ctx = self.get('?category=unknown&page=999', [self.row('inspection:1')])
        self.assertEqual(ctx['selected_category'], '')
        self.assertEqual(ctx['history_page'].page, 1)
        response, ctx = self.get('?category=maintenance', [])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ctx['history_page'].total, 0)

    def test_real_rows_company_boundary_and_no_csv_or_membership_fabrication(self):
        m = self.m
        m.db.session.add(m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            content='Visible maintenance', status='完了'))
        m.db.session.add(m.VehicleMaintenanceRecord(company_code='OTHER', vehicle_record_id=self.vehicle.id,
            content='PRIVATE_OTHER_COMPANY', status='完了'))
        m.db.session.add(m.VehicleOperationImportDraft(id='private-csv', company_code='TEST',
            created_by_username='someone', source_filename='PRIVATE_PREVIEW', source_file=b'private',
            status='preview', result_json='{}'))
        m.db.session.commit()
        response, ctx = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.counts(ctx), {'':1, 'inspection':0, 'maintenance':1, 'other':0})
        body = response.get_data(as_text=True)
        self.assertNotIn('PRIVATE_', body)
        self.assertNotIn('所属・担当変更', body)
        self.assertNotIn('運行実績を取り込み', body)
        self.assertEqual(self.client.get('/master/vehicles/999999/karte/history').status_code, 404)
