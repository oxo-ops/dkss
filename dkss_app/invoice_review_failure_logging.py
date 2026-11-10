"""Bounded diagnostics for invoice review failures, without SQL or payloads."""
from sqlalchemy.exc import DataError, IntegrityError, OperationalError, SQLAlchemyError, StatementError


def log_invoice_review_failure(logger, *, action, error):
    # Use only known internal actions and fixed categories. Do not format the
    # exception or its class name: either can contain SQL parameters or secrets.
    action = action if type(action) is str and action in (
        'already_recorded', 'initial_cost', 'additional_cost', 'correction', 'parts_review',
    ) else 'unknown'
    if isinstance(error, IntegrityError):
        category = 'integrity'
    elif isinstance(error, OperationalError):
        category = 'operational'
    elif isinstance(error, DataError):
        category = 'data'
    elif isinstance(error, StatementError):
        category = 'statement'
    elif isinstance(error, SQLAlchemyError):
        category = 'database'
    else:
        category = 'unexpected'
    logger.error('INVOICE_REVIEW_FAILED action=%s error_type=%s', action, category)
