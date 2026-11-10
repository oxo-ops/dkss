"""Invoice-review error logs must not expose SQL, parameters or private details.

Real Flask requests and disposable SQLite transactions exercise all five review
modes. Only the commit failure is injected; writes are flushed before failing.
"""
from contextlib import contextmanager
from decimal import Decimal
import json
import logging
import unittest
from unittest.mock import patch

from sqlalchemy.exc import OperationalError

import test_q07_invoice_lifecycle as lifecycle


ACTIONS = ('already_recorded', 'initial_cost', 'additional_cost', 'correction', 'parts_review')
SQL_CANARY = 'SYNTHETIC_INVOICE_SQL_CANARY'
PARAM_CANARY = 'SYNTHETIC_INVOICE_PARAMETER_CANARY'
PRIVATE_CANARY = 'SYNTHETIC_INVOICE_PRIVATE_CANARY'
CANARIES = (SQL_CANARY, PARAM_CANARY, PRIVATE_CANARY)


@contextmanager
def captured_errors(logger):
    """Attach a real formatter/handler, including traceback formatting if present."""
    records, rendered = [], []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)
            rendered.append(self.format(record))

    handler = Capture(logging.ERROR)
    handler.setFormatter(logging.Formatter('%(levelname)s:%(message)s'))
    handlers, propagate, level = logger.handlers[:], logger.propagate, logger.level
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.ERROR)
    try:
        yield records, rendered
    finally:
        logger.handlers = handlers
        logger.propagate = propagate
        logger.setLevel(level)


class InvoiceReviewSafeLoggingRoutes(unittest.TestCase):
    setUpClass = classmethod(lifecycle.InvoiceLifecycleTests.setUpClass.__func__)
    tearDownClass = classmethod(lifecycle.InvoiceLifecycleTests.tearDownClass.__func__)
    setUp = lifecycle.InvoiceLifecycleTests.setUp
    tearDown = lifecycle.InvoiceLifecycleTests.tearDown
    target = lifecycle.InvoiceLifecycleTests.target
    invoice = lifecycle.InvoiceLifecycleTests.invoice
    review = lifecycle.InvoiceLifecycleTests.review
    assert_originals = lifecycle.InvoiceLifecycleTests.assert_originals

    def prepare_review(self, action):
        row = self.target(None if action in {'initial_cost', 'correction'} else '500')
        replacement, originals = None, []
        if action == 'correction':
            replacement, original, _ = self.invoice(row, '100')
            originals.append(original)
            self.assertEqual(self.review(replacement, 'initial_cost').status_code, 302)
        document, draft, _ = self.invoice(row, '60' if action == 'correction' else '100')
        originals.append(draft)
        part = self.m.VehiclePartReplacement(
            company_code='TEST', vehicle_record_id=self.vehicle.id,
            maintenance_record_id=row.id, part_name='Existing synthetic part',
            part_number='EXISTING-PART', quantity=2, replacement_date=row.entry_date,
            cost=Decimal('12.00'), created_at='2026-01-01T00:00:00+09:00')
        self.m.db.session.add(part)
        if action == 'parts_review':
            payload = json.loads(document.payload_json)
            payload['line_items'] = [{'description': 'Synthetic new part', 'parts_amount': '15'}]
            preview = json.loads(draft.preview_json)
            preview['records'][document.source_record_index] = payload
            draft.preview_json = json.dumps(preview)
            document.payload_json = json.dumps(payload)
            document.parts_status = 'pending'
        self.m.db.session.commit()
        if action == 'already_recorded':
            suffix, data = 'duplicate', {'already_recorded': '1'}
        elif action == 'parts_review':
            from dkss_app.vehicle_documents import vehicle_invoice_parts_version
            suffix, data = 'parts', {
                'confirm_parts': '1', 'parts_version': vehicle_invoice_parts_version([part]),
                'part_choice_0': 'new', 'part_name_0': 'Synthetic new part',
                'part_number_0': 'NEW-PART', 'part_quantity_0': '1',
                'replacement_date': row.entry_date, 'replacement_mileage': '12000'}
        else:
            suffix, data = action.replace('_', '-'), {'confirm_' + action: '1'}
            if action != 'initial_cost':
                data['expected_total'] = str(row.total_cost)
            if replacement is not None:
                data['replaces_document_id'] = replacement.id
        return {
            'row': row, 'document': document, 'originals': originals,
            'replacement': replacement, 'existing_part': part,
            'url': '/master/vehicles/invoice-reviews/' + document.id + '/' + suffix,
            'data': data,
        }

    def snapshot(self):
        """Reload every persisted column, including source bytes and review history."""
        self.m.db.session.expire_all()
        result = {}
        for name in ('VehicleMaintenanceRecord', 'VehicleMaintenanceDocument',
                     'VehicleDocumentImportDraft', 'VehicleMaintenanceRecordEvent',
                     'VehiclePartReplacement', 'VehiclePartReplacementSource'):
            model = getattr(self.m, name)
            result[name] = [tuple(getattr(row, column.name) for column in model.__table__.columns)
                            for row in model.query.order_by(model.id).all()]
        return result

    def post_review(self, prepared, *, validation_only=False, data=None):
        return self.client.post(prepared['url'], data=prepared['data'] if data is None else data,
                                headers={'X-DKSS-Validation-Only' if validation_only
                                         else 'X-DKSS-Final-Submit': '1'})

    def exercise_failure(self, action):
        prepared = self.prepare_review(action)
        before = self.snapshot()
        document = prepared['document']
        previous_history = len(json.loads(document.decision_json).get('review_history', []))
        event_count = self.m.VehicleMaintenanceRecordEvent.query.count()
        staged = []

        def fail_after_real_flush():
            self.m.db.session.flush()
            staged.append(self.snapshot())
            raise OperationalError('UPDATE ' + SQL_CANARY + ' SET value = :value',
                                   {'value': PARAM_CANARY}, RuntimeError(PRIVATE_CANARY))

        with captured_errors(self.m.app.logger) as (records, rendered), \
                patch.object(self.m.db.session, 'commit', side_effect=fail_after_real_flush) as commit, \
                patch.object(self.m.db.session, 'rollback', wraps=self.m.db.session.rollback) as rollback:
            response = self.post_review(prepared)
        self.assertEqual(commit.call_count, 1)
        self.assertEqual(rollback.call_count, 1)
        self.assertEqual(len(staged), 1)
        self.assertNotEqual(staged[0], before, 'The injected failure must follow real writes.')
        self.assertEqual(response.status_code, 500)
        message = ('確認結果を保存できませんでした。再度お試しください。' if action == 'already_recorded'
                   else '交換部品を保存できませんでした。再度お試しください。' if action == 'parts_review'
                   else '費用を保存できませんでした。再度お試しください。')
        self.assertEqual(response.json, {'errors': [{'message': message, 'field': ''}]})
        self.assertEqual(response.headers['X-DKSS-Form-Errors'], '1')
        self.assertEqual(self.snapshot(), before, 'Rollback must restore every persisted column.')
        self.assert_originals(*prepared['originals'])
        with captured_errors(self.m.app.logger) as (retry_records, _):
            retry = self.post_review(prepared)
        self.assertEqual(retry.status_code, 302)
        self.assertEqual(retry_records, [])
        self.m.db.session.expire_all()
        self.assertEqual(prepared['row'].total_cost, Decimal({
            'already_recorded': '500', 'initial_cost': '100', 'additional_cost': '600',
            'correction': '60', 'parts_review': '500'}[action]))
        self.assertEqual(document.financial_status,
                         'duplicate' if action == 'already_recorded' else
                         'pending' if action == 'parts_review' else 'confirmed')
        self.assertEqual(len(json.loads(document.decision_json)['review_history']), previous_history + 1)
        self.assertEqual(json.loads(document.decision_json)['review_history'][-1]['action'], action)
        self.assertEqual(self.m.VehicleMaintenanceRecordEvent.query.count(),
                         event_count + (action in {'initial_cost', 'additional_cost', 'correction'}))
        self.assertEqual(self.m.VehiclePartReplacement.query.count(), 2 if action == 'parts_review' else 1)
        self.assertEqual(prepared['existing_part'].part_number, 'EXISTING-PART')
        if action == 'correction':
            self.assertEqual(prepared['replacement'].financial_status, 'superseded')
            self.assertEqual(document.related_document_id, prepared['replacement'].id)
        after_retry = self.snapshot()
        with captured_errors(self.m.app.logger) as (replay_records, _):
            replay = self.post_review(prepared)
        self.assertEqual(replay.status_code, 302 if action == 'already_recorded' else 400)
        self.assertEqual(self.snapshot(), after_retry, 'A replay must never apply the decision twice.')
        self.assertEqual(replay_records, [])
        self.assert_originals(*prepared['originals'])

        # Keep confidentiality assertions last: baseline failure still proves that
        # rollback, generic response, retry and replay checks all ran successfully.
        text = '\n'.join(rendered)
        self.failure_observation = {
            'action': action, 'status_code': response.status_code,
            'content_type': response.content_type, 'body_hex': response.data.hex(),
            'commit_calls': commit.call_count, 'rollback_calls': rollback.call_count,
            'rollback_state_restored': True, 'originals_preserved': True,
            'retry_status': retry.status_code, 'replay_status': replay.status_code,
            'replay_state_unchanged': True,
            'canary_leaks': {canary: canary in text for canary in CANARIES},
            'traceback_present': any(record.exc_info is not None for record in records),
        }
        for canary in CANARIES:
            self.assertFalse(canary in text, 'Synthetic exception canary leaked for ' + action)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.levelno, logging.ERROR)
        self.assertEqual(record.getMessage(), 'INVOICE_REVIEW_FAILED action=' + action + ' error_type=operational')
        self.assertEqual(record.msg, 'INVOICE_REVIEW_FAILED action=%s error_type=%s')
        self.assertEqual(record.args, (action, 'operational'))
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.exc_text)
        self.assertIsNone(record.stack_info)

    def test_already_recorded_failure_is_safe_atomic_and_retryable(self):
        self.exercise_failure('already_recorded')

    def test_initial_cost_failure_is_safe_atomic_and_retryable(self):
        self.exercise_failure('initial_cost')

    def test_additional_cost_failure_is_safe_atomic_and_retryable(self):
        self.exercise_failure('additional_cost')

    def test_correction_failure_is_safe_atomic_and_retryable(self):
        self.exercise_failure('correction')

    def test_parts_review_failure_is_safe_atomic_and_retryable(self):
        self.exercise_failure('parts_review')

    def test_validation_only_does_not_commit_or_log_failure(self):
        for action in ACTIONS:
            with self.subTest(action=action):
                prepared = self.prepare_review(action)
                before = self.snapshot()
                with captured_errors(self.m.app.logger) as (records, _), \
                        patch.object(self.m.db.session, 'commit') as commit:
                    response = self.post_review(prepared, validation_only=True)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json, {'ok': True})
                commit.assert_not_called()
                self.assertEqual(records, [])
                self.assertEqual(self.snapshot(), before)
                self.assert_originals(*prepared['originals'])

    def test_invalid_confirmation_does_not_commit_or_log_failure(self):
        for action in ACTIONS:
            with self.subTest(action=action):
                prepared = self.prepare_review(action)
                before = self.snapshot()
                with captured_errors(self.m.app.logger) as (records, _), \
                        patch.object(self.m.db.session, 'commit') as commit:
                    response = self.post_review(prepared, data={})
                self.assertEqual(response.status_code, 400)
                commit.assert_not_called()
                self.assertEqual(records, [])
                self.assertEqual(self.snapshot(), before)

    def test_company_boundary_does_not_commit_or_log_failure(self):
        for action in ACTIONS:
            with self.subTest(action=action):
                prepared = self.prepare_review(action)
                prepared['document'].company_code = 'OTHER'
                self.m.db.session.commit()
                before = self.snapshot()
                with captured_errors(self.m.app.logger) as (records, _), \
                        patch.object(self.m.db.session, 'commit') as commit:
                    response = self.post_review(prepared)
                self.assertEqual(response.status_code, 404)
                commit.assert_not_called()
                self.assertEqual(records, [])
                self.assertEqual(self.snapshot(), before)

    def test_unauthorized_user_does_not_commit_or_log_failure(self):
        prepared_reviews = [self.prepare_review(action) for action in ACTIONS]
        self.m.User.query.filter_by(company_code='TEST', username='admin').one().role = 'user'
        self.m.db.session.commit()
        with self.client.session_transaction() as session:
            session['role'] = 'user'
        before = self.snapshot()
        for action, prepared in zip(ACTIONS, prepared_reviews):
            with self.subTest(action=action), captured_errors(self.m.app.logger) as (records, _), \
                    patch.object(self.m.db.session, 'commit') as commit:
                response = self.post_review(prepared)
                # The real before-request master guard redirects non-admins.
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.location, '/')
                commit.assert_not_called()
                self.assertEqual(records, [])
                self.assertEqual(self.snapshot(), before)

if __name__ == '__main__':
    unittest.main()
