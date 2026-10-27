"""Q05 operation chronology, using synthetic CSV and an isolated database."""
import csv
import io
import unittest

from upload_validation import UploadValidationError
from vehicle_operation_csv import parse_vehicle_operation_csv_row, parse_vehicle_operation_date
from test_workflow_regressions import WorkflowRegressionTests as _Base


class OperationChronologyTests(unittest.TestCase):
    def row(self, departure, arrival):
        return {'日報番号': 'Q05-TEST', '運行日': '2028-02-29',
                '出庫日時': departure, '入庫日時': arrival}

    def test_reversed_times_rejected_with_source_line(self):
        for departure, arrival in [
            ('2026/10/27 09:00:01', '2026/10/27 09:00:00'),
            ('2027-01-01 00:00:00', '2026-12-31 23:59:59'),
            ('2028-03-01 00:00:00', '2028-02-29 23:59:59'),
        ]:
            with self.subTest(departure=departure, arrival=arrival):
                with self.assertRaisesRegex(UploadValidationError, 'CSVの8行目：.*入庫日時.*出庫日時'):
                    parse_vehicle_operation_csv_row(self.row(departure, arrival), 8)

    def test_overnight_year_end_and_leap_day_keep_full_dates(self):
        for departure, arrival in [
            ('2026/10/27 23:59:59', '2026/10/28 00:00:00'),
            ('2026-12-31 23:59:59', '2027-01-01 00:00:00'),
            ('2028-02-29 23:59:59', '2028-03-01 00:00:00'),
        ]:
            with self.subTest(departure=departure):
                row = parse_vehicle_operation_csv_row(self.row(departure, arrival), 8)
                self.assertEqual(row['departure_at'], departure.replace('/', '-'))
                self.assertEqual(row['arrival_at'], arrival.replace('/', '-'))

    def test_same_instant_and_optional_times_are_preserved(self):
        for departure, arrival in [('', ''), (None, None),
            ('2028-02-29 23:59', ''), ('', '2028-03-01 00:00'),
            ('2028/02/29 10:00', '2028-02-29 10:00:00')]:
            with self.subTest(departure=departure, arrival=arrival):
                row = parse_vehicle_operation_csv_row(self.row(departure, arrival), 8)
                if not departure:
                    self.assertIsNone(row['departure_at'])
                if not arrival:
                    self.assertIsNone(row['arrival_at'])
                self.assertEqual(row['operation_date'], '2028-02-29')

    def test_normalized_years_are_four_digits_on_every_platform(self):
        for year in ('0001', '0999', '1000', '2000'):
            with self.subTest(year=year):
                self.assertEqual(parse_vehicle_operation_date(year + '/01/01', '運行日'), year + '-01-01')
                self.assertEqual(parse_vehicle_operation_date(year + '/01/01 00:00', '出庫日時', with_time=True),
                                 year + '-01-01 00:00:00')
        row = parse_vehicle_operation_csv_row(self.row('0999-12-31 23:59:59', '1000-01-01 00:00:00'), 8)
        self.assertLess(row['departure_at'], row['arrival_at'])

    def test_invalid_calendar_is_rejected_before_chronology(self):
        for value in ('2026-02-29 10:00', '1900-02-29 10:00', '2026-04-31 10:00', '2026-01-01 24:00'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(UploadValidationError, '出庫日時の日付・時刻'):
                    parse_vehicle_operation_csv_row(self.row(value, '2028-03-01 00:00'), 8)


class OperationChronologyRouteTests(unittest.TestCase):
    setUpClass = classmethod(_Base.setUpClass.__func__)
    tearDownClass = classmethod(_Base.tearDownClass.__func__)
    setUp = _Base.setUp
    tearDown = _Base.tearDown

    def draft(self, rows):
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['日報番号', '運行日', '車両コード', '出庫日時', '入庫日時'])
        for index, (departure, arrival) in enumerate(rows):
            writer.writerow([f'Q05-{index}', '2028-02-29', 'TEST-CODE', departure, arrival])
        source = stream.getvalue().encode('utf-8-sig')
        draft = self.m.VehicleOperationImportDraft(id='q05-dates', company_code='TEST',
            created_by_username='admin', source_filename='q05.csv', source_file=source, status='preview')
        self.m.db.session.add(draft)
        self.m.db.session.commit()
        return draft

    def submit(self, count):
        return {'include': [str(i) for i in range(2, count + 2)],
                'confirmed_vehicle_mapping': [f'{i}:{self.vehicle.id}' for i in range(2, count + 2)],
                **{f'vehicle_{i}': str(self.vehicle.id) for i in range(2, count + 2)}}

    def test_direct_confirmation_rejects_reverse_without_importing(self):
        draft = self.draft([('2028-02-29 11:00', '2028-02-29 10:00')])
        response = self.client.post(f'/vehicle/operation-import/{draft.id}/confirm',
            data=self.submit(1), headers={'X-DKSS-Final-Submit': '1'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('入庫日時', response.json['errors'][0]['message'])
        self.assertEqual(self.m.VehicleOperationRecord.query.count(), 0)
        self.m.db.session.refresh(draft)
        self.assertEqual(draft.status, 'preview')
        self.assertNotIn('imported', draft.result_json or '')
        self.assertEqual(self.m.VehicleOperationVehicleMapping.query.count(), 0)

    def test_selected_mixed_rows_do_not_partially_import(self):
        draft = self.draft([('2028-02-29 23:00', '2028-03-01 00:00'),
                            ('2028-02-29 11:00', '2028-02-29 10:00')])
        response = self.client.post(f'/vehicle/operation-import/{draft.id}/confirm',
            data=self.submit(2), headers={'X-DKSS-Final-Submit': '1'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.m.VehicleOperationRecord.query.count(), 0)
        self.assertEqual(self.m.VehicleOperationVehicleMapping.query.count(), 0)

    def test_overnight_same_instant_and_missing_time_import(self):
        draft = self.draft([('2028-02-29 23:00', '2028-03-01 00:00'),
                            ('2028-02-29 10:00', '2028-02-29 10:00'),
                            ('', '2028-03-01 00:00'), ('', '')])
        response = self.client.post(f'/vehicle/operation-import/{draft.id}/confirm', data=self.submit(4))
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        rows = self.m.VehicleOperationRecord.query.order_by(self.m.VehicleOperationRecord.report_number).all()
        self.assertEqual(len(rows), 4)
        self.assertEqual((rows[0].departure_at, rows[0].arrival_at),
                         ('2028-02-29 23:00:00', '2028-03-01 00:00:00'))
        self.assertIsNone(rows[2].departure_at)
        self.assertIsNone(rows[3].arrival_at)
        self.m.db.session.refresh(draft)
        self.assertEqual(draft.status, 'completed')


del _Base  # Prevent unittest discovery from collecting the imported fixture class.

if __name__ == '__main__':
    unittest.main()
