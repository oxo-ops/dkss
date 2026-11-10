"""Invoice failure diagnostics keep only explicitly bounded metadata."""
import io
import logging
import unittest

from sqlalchemy.exc import DataError, IntegrityError, OperationalError, SQLAlchemyError, StatementError
from dkss_app.invoice_review_failure_logging import log_invoice_review_failure


class InvoiceReviewLoggingMetadataTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.records = []
        self.logger = logging.Logger('isolated-invoice-metadata', logging.ERROR)
        self.logger.propagate = False
        self.logger.addHandler(logging.StreamHandler(self.output))
        handler = logging.Handler()
        handler.emit = self.records.append
        self.logger.addHandler(handler)

    def emit(self, action, error):
        self.output.seek(0)
        self.output.truncate(0)
        self.records.clear()
        log_invoice_review_failure(self.logger, action=action, error=error)
        self.assertEqual(len(self.records), 1)
        record = self.records[0]
        self.assertEqual(record.levelno, logging.ERROR)
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.exc_text)
        self.assertIsNone(record.stack_info)
        self.assertNotIn('PRIVATE_CANARY', self.output.getvalue())
        return self.output.getvalue().strip()

    def test_all_actions_and_categories_are_fixed_and_diagnostic(self):
        for action in ('already_recorded', 'initial_cost', 'additional_cost', 'correction', 'parts_review'):
            for cls, category in ((IntegrityError, 'integrity'), (OperationalError, 'operational'),
                                  (DataError, 'data'), (StatementError, 'statement')):
                with self.subTest(action=action, category=category):
                    if cls is StatementError:
                        error = cls('PRIVATE_CANARY message', 'PRIVATE_CANARY SQL',
                                    {'private': 'PRIVATE_CANARY params'}, RuntimeError('PRIVATE_CANARY original'))
                    else:
                        error = cls('PRIVATE_CANARY SQL', {'private': 'PRIVATE_CANARY params'},
                                    RuntimeError('PRIVATE_CANARY original'))
                    error.__cause__ = RuntimeError('PRIVATE_CANARY cause')
                    self.assertEqual(self.emit(action, error),
                        f'INVOICE_REVIEW_FAILED action={action} error_type={category}')

    def test_generic_database_and_unexpected_classes_do_not_format_payloads(self):
        for error, category in ((SQLAlchemyError('PRIVATE_CANARY SQLAlchemy'), 'database'),
                                (RuntimeError('PRIVATE_CANARY runtime'), 'unexpected')):
            with self.subTest(category=category):
                self.assertEqual(self.emit('correction', error),
                    'INVOICE_REVIEW_FAILED action=correction error_type=' + category)

    def test_exception_class_name_and_str_are_not_used(self):
        def forbidden_str(self):
            raise AssertionError('Exception formatting is forbidden')
        error_type = type('PRIVATE_CANARY_DYNAMIC_TYPE', (SQLAlchemyError,), {'__str__': forbidden_str})
        self.assertEqual(self.emit('parts_review', error_type('PRIVATE_CANARY')),
                         'INVOICE_REVIEW_FAILED action=parts_review error_type=database')

    def test_unrecognized_action_values_fail_closed(self):
        class Hostile:
            def __str__(self):
                raise AssertionError('Action formatting is forbidden')
            def __eq__(self, other):
                raise AssertionError('Action comparison is forbidden')
        for action in (None, True, 123, [], {}, Hostile(), 'PRIVATE_CANARY', 'correction\nPRIVATE_CANARY'):
            with self.subTest(type=type(action).__name__):
                self.assertEqual(self.emit(action, SQLAlchemyError('PRIVATE_CANARY')),
                    'INVOICE_REVIEW_FAILED action=unknown error_type=database')

    def test_even_allowlisted_str_subclass_is_not_formatted(self):
        class HostileStr(str):
            def __str__(self):
                raise AssertionError('Subclass formatting is forbidden')
            def __eq__(self, other):
                raise AssertionError('Subclass comparison is forbidden')
        self.assertEqual(self.emit(HostileStr('initial_cost'), SQLAlchemyError('PRIVATE_CANARY')),
            'INVOICE_REVIEW_FAILED action=unknown error_type=database')


if __name__ == '__main__':
    unittest.main()
