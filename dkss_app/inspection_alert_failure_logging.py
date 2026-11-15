"""Fixed metadata for inspection reminder failures; no SQL or exception payloads."""
from sqlalchemy.exc import SQLAlchemyError


def log_inspection_alert_failure(logger, *, mode, error):
    mode = mode if type(mode) is str and mode in ('poll', 'command', 'watch') else 'unknown'
    if isinstance(error, SQLAlchemyError):
        category = 'database'
    elif isinstance(error, ValueError):
        category = 'input'
    elif isinstance(error, RuntimeError):
        category = 'runtime'
    else:
        category = 'unexpected'
    logger.error('INSPECTION_ALERT_FAILED mode=%s error_type=%s', mode, category)
