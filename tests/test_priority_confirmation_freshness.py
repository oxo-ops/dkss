"""Real certificate reader and normal input/GET/feedback across Japan midnight.

No projection or input builder is stubbed. Only the clock advances together;
source PDF and account/session records are isolated synthetic fixtures.
"""
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_priority_certificate_sources as certificate
from vehicle_priority_inputs import generation_priority_inputs, validate_priority_input


class LegalConfirmationFreshnessTests(unittest.TestCase):
    setUpClass = classmethod(certificate.CertificateSourceTests.setUpClass.__func__)
    tearDownClass = classmethod(certificate.CertificateSourceTests.tearDownClass.__func__)
    setUp = certificate.CertificateSourceTests.setUp
    tearDown = certificate.CertificateSourceTests.tearDown
    request = certificate.CertificateSourceTests.request
    login = certificate.CertificateSourceTests.login
    add_document = certificate.CertificateSourceTests.add_document
    post_preview = certificate.CertificateSourceTests.post_preview
    confirm_http = certificate.CertificateSourceTests.confirm_http

    def test_real_next_day_input_and_cancel_reject_old_feedback_without_rewriting_saved_analysis(self):
        from dkss_app.analysis import get_vehicle_karte_analysis_job_data
        self.confirm_http()
        def inputs():
            with self.app.test_request_context('/'):
                return get_vehicle_karte_analysis_job_data(self.vehicle)
        payload, sources = inputs()
        offer = next(v for v in generation_priority_inputs(payload).values() if v['kind'] == 'confirmed_priority')
        item = dict(priority='低', category='整備・点検', target=offer['display_target'],
            title='期限と適用を確認', action='責任者が対応を確認', source_ids=offer['source_ids'], priority_input_ref=offer['ref'])
        validate_priority_input(item, payload)
        self.assertEqual(item['priority'], '高')
        bundle = dict(analysis={'recommendations': [item]}, sources=sources, fingerprints=payload['_fingerprints'])
        saved = self.models.VehicleKarteAnalysis(company_code='A', vehicle_record_id=self.vehicle.id,
            status='completed', result_json=json.dumps(bundle, ensure_ascii=False))
        self.db.session.add(saved); self.db.session.commit()
        original = saved.result_json
        api = f'/vehicle/karte/{self.vehicle.id}/analysis/result'
        initial = self.request('GET', api).json
        self.assertTrue(initial['is_current'])
        shown = initial['analysis']['recommendations'][0]
        self.assertEqual(shown['priority_assessment']['effective_score'], 60)
        answer = dict(status='accepted', proposal_id=shown['proposal_id'], proposal_revision=shown['proposal_revision'])
        tomorrow = self.day + timedelta(days=1)
        instant = datetime.combine(tomorrow, datetime.min.time().replace(hour=9), ZoneInfo('Asia/Tokyo'))
        class NextDay(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
        with patch('dkss_app.priority_certificate_sources._today', return_value=tomorrow), \
                patch('dkss_app.priority_confirmations._day', return_value=tomorrow), \
                patch('dkss_app.priority_confirmations.datetime', NextDay), \
                patch('dkss_app.priority_confirmed_projection.datetime', NextDay), \
                patch('dkss_app.priority_projection.datetime', NextDay), \
                patch('dkss_app.common.datetime', NextDay):
            next_payload, _ = inputs()
            self.assertNotEqual(payload['_fingerprints']['important_hash'], next_payload['_fingerprints']['important_hash'])
            held = self.request('GET', api).json
            self.assertFalse(held['is_current'])
            value = held['analysis']['recommendations'][0]
            self.assertEqual(value['priority'], '高')
            self.assertIsNone(value['priority_assessment']['effective_score'])
            self.assertEqual(self.request('POST', api.replace('/result', '/feedback'), json=answer).status_code, 409)
            prefix = f'/vehicle/karte/{self.vehicle.id}/priority-confirmations'
            history = self.request('GET', prefix, query_string={'kind': 'legal_deadline'}).json['history']
            self.assertEqual(history[0]['status'], 'held')
            self.assertEqual(self.request('POST', prefix, json={'token': history[0]['cancel_token']}).status_code, 200)
            cancelled, _ = inputs()
            self.assertNotEqual(next_payload['_fingerprints']['important_hash'], cancelled['_fingerprints']['important_hash'])
            self.assertEqual(self.request('GET', api).json['analysis']['recommendations'], [])
            self.assertEqual(self.request('POST', api.replace('/result', '/feedback'), json=answer).status_code, 409)
        self.assertEqual(saved.result_json, original)
        self.assertEqual(self.vehicle.inspection_expiry, self.day.isoformat())
        self.assertEqual(self.models.VehicleChecklistResult.query.count(), 0)
        self.assertEqual(self.models.Notification.query.count(), 0)
