"""Offline app and sample-based assertions; no AI accuracy measurement."""
from io import BytesIO
import json
import unittest
from unittest.mock import patch

import test_document_import_queue as fixture
from test_vehicle_certificate_ai import FakeResponse
from test_inspection_document_ai import pdf_bytes
import vehicle_certificate_ai as certificate


class DocumentIntakeVehicleSpec(unittest.TestCase):
    setUpClass = classmethod(fixture.DocumentImportQueueTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.DocumentImportQueueTests.tearDownClass.__func__)
    setUp = fixture.DocumentImportQueueTests.setUp
    tearDown = fixture.DocumentImportQueueTests.tearDown
    send = fixture.DocumentImportQueueTests.send
    worker = fixture.DocumentImportQueueTests.worker
    inspection_form = fixture.DocumentImportQueueTests.inspection_form

    def set_full_plate(self, vehicle):
        vehicle.plate_area = '品川'
        vehicle.plate_class = '010'
        vehicle.plate_kana = 'あ'
        vehicle.plate_number = '0012'

    def read(self, **record_fields):
        self.assertEqual(self.send().status_code, 202)
        self.assertTrue(self.worker(record_fields=record_fields))
        draft = fixture.Draft.query.one()
        self.assertEqual(draft.status, 'preview')
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 0)
        return draft, json.loads(draft.preview_json)['records'][0]

    def confirm(self, draft, **kwargs):
        response = self.client.post(
            f'/vehicle/data-import/{draft.batch_id}/confirm',
            data=self.inspection_form(draft, **kwargs),
        )
        self.assertEqual(response.status_code, 302)
        self.m.db.session.refresh(draft)
        return json.loads(draft.result_json)

    def expect_parked_without_karte_link(self, draft, *vehicles):
        result = self.confirm(draft, vehicle=False)
        self.assertEqual(result['records'], [])
        self.assertEqual(result['pending_count'], 1)
        group = self.m.VehicleImportPending.query.one()
        item = self.m.VehicleImportPendingRecord.query.one()
        self.assertEqual(item.document_draft_id, draft.id)
        self.assertEqual(group.status, 'pending')
        self.assertIsNone(group.resolved_vehicle_id)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 0)
        for vehicle in vehicles:
            prefix = f'/vehicle/karte/{vehicle.id}/documents'
            self.assertNotIn(draft.source_filename, self.client.get(prefix).get_data(as_text=True))
            self.assertEqual(self.client.get(f'{prefix}/{draft.id}/source').status_code, 404)
        response = self.client.get(
            f'/master/vehicles/pending/{group.id}/document-sources/{draft.id}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, draft.source_file)

    def test_null_chassis_legacy_vehicle_matches_complete_unique_plate_and_preserves_null(self):
        self.vehicle.chassis_number = None
        self.set_full_plate(self.vehicle)
        self.m.db.session.commit()
        draft, row = self.read(chassis_number='DOCUMENT-ONLY-NEW')
        self.assertEqual(row['vehicle_match_status'], 'matched')
        self.assertEqual(row['vehicle_record_id'], self.vehicle.id)
        result = self.confirm(draft)
        self.assertEqual(result['pending_count'], 0)
        self.assertEqual(result['records'][0]['vehicle_record_id'], self.vehicle.id)
        self.m.db.session.refresh(self.vehicle)
        self.assertIsNone(self.vehicle.chassis_number)
        source = self.client.get(f'/vehicle/karte/{self.vehicle.id}/documents/{draft.id}/source')
        self.assertEqual(source.status_code, 200)
        self.assertEqual(source.data, draft.source_file)

    def test_number_suffix_with_sparse_legacy_master_remains_pending_and_unattached(self):
        self.vehicle.chassis_number = None
        self.vehicle.plate_number = '0012'
        self.m.db.session.commit()
        draft, row = self.read(chassis_number=None, registration_number='0012')
        self.assertEqual(row['vehicle_match_status'], 'unmatched')
        self.assertIsNone(row['vehicle_record_id'])
        self.expect_parked_without_karte_link(draft, self.vehicle)

    def test_chassis_and_full_plate_on_different_vehicles_remain_pending_and_unattached(self):
        other = self.m.Vehicle(company_code='TEST', chassis_number='TEST-002')
        self.set_full_plate(other)
        self.m.db.session.add(other)
        self.m.db.session.commit()
        draft, row = self.read()
        self.assertEqual(row['vehicle_match_status'], 'conflict')
        self.assertIsNone(row['vehicle_record_id'])
        self.expect_parked_without_karte_link(draft, self.vehicle, other)


class VehicleRegistrationCertificateSpec(unittest.TestCase):
    setUpClass = classmethod(fixture.DocumentImportQueueTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.DocumentImportQueueTests.tearDownClass.__func__)
    setUp = fixture.DocumentImportQueueTests.setUp
    tearDown = fixture.DocumentImportQueueTests.tearDown

    def extract_mock(self, mocked_vehicle, filename):
        raw = pdf_bytes()
        vehicle = dict.fromkeys(certificate.FIELDS)
        vehicle.update(mocked_vehicle)
        payload = {'status': 'completed', 'output': [{'content': [{
            'type': 'output_text',
            'text': json.dumps({'vehicle': vehicle, 'warnings': []}),
        }]}]}
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'isolated-fake-key'}), patch.object(
            certificate.urllib.request, 'urlopen', return_value=FakeResponse(payload)
        ) as provider:
            response = self.client.post(
                '/master/vehicles/certificate/extract',
                data={'certificate': (BytesIO(raw), filename)},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['needs_review'])
        self.assertEqual(provider.call_args.kwargs['timeout'], 180)
        self.assertIs(json.loads(provider.call_args.args[0].data)['store'], False)
        return raw, response.json['vehicle']

    def test_certificate_pending_keeps_sample_scope_until_vehicle_registration(self):
        # Expected fields from MLIT sample layout; blank PDF + stub are deliberate.
        common = {
            'plate_area': '札幌', 'plate_class': '300', 'plate_kana': 'お',
            'plate_number': '9999', 'chassis_number': 'R35-DSG-00001',
            'model_code': 'CBA-R35', 'engine_code': 'VR38',
            'manufacturer': 'ニッサン', 'first_registration_date': '2021-05',
            'inspection_expiry': '2024-05-09', 'gross_vehicle_weight': '1950',
            'type_designation_number': '15965', 'type_classification_number': '0001',
        }
        for flavor, shape in [('A', '箱型'), ('B', '事故調査用緊急セミトレーラ')]:
            with self.subTest(flavor=flavor):
                raw, form = self.extract_mock(
                    dict(common, body_type=shape, type='推測した社内車種'),
                    f'sample_{flavor}.pdf',
                )
                self.assertEqual({key: form[key] for key in common}, common)
                self.assertEqual(form['body_type'], shape)
                self.assertEqual(form['max_payload'], '')
                self.assertEqual(form['type'], '')
                self.assertEqual(form['office'], '')
                self.assertEqual(self.m.Vehicle.query.count(), 1)
                row = fixture.Draft.query.filter_by(source_filename=f'sample_{flavor}.pdf').one()
                self.assertEqual(row.status, 'certificate_pending')
                self.assertEqual(row.source_file, raw)
                self.assertEqual(json.loads(row.result_json), {})
                self.assertEqual(
                    self.client.get(f'/vehicle/karte/{self.vehicle.id}/documents/{row.id}/source').status_code,
                    404,
                )


if __name__ == '__main__':
    unittest.main()
