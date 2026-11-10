"""Bounded metadata for caught document import failures, without private payloads."""
from sqlalchemy.exc import SQLAlchemyError


_SAFE_ERROR_CODES = frozenset({
    'API_KEY_NOT_SET', 'OPENAI_NETWORK_OR_TIMEOUT', 'NO_INVOICE_FOUND',
    'NO_INSPECTION_FOUND', 'NO_DRIVING_REPORT_FOUND', 'INVALID_DRIVING_REPORT_PDF',
    'INVALID_DRIVING_REPORT_EXTRACTION', 'INVALID_INSPECTION_PDF',
    'INVALID_INSPECTION_EXTRACTION', 'OCR_NO_RECORDS', 'DOCUMENT_TOO_LARGE',
    'CONVERTED_PDF_TOO_LARGE', 'IMAGE_TOO_LARGE', 'IMAGE_READ_FAILED',
    'INVALID_SOURCE_PAGES', 'EXTRACTION_NOT_COMPLETED',
})


def log_document_import_failure(logger, *, mode, stage, error, code=None):
    # Do not stringify exceptions or log their class names: either can contain
    # source names, OCR/provider content, SQL parameters or credentials. Retain
    # a code only when a caller has already extracted an exact known value.
    mode = mode if type(mode) is str and mode in ('form', 'progress') else 'unknown'
    stage = stage if type(stage) is str and stage in ('extract', 'process', 'persist') else 'unknown'
    code = code if type(code) is str and code in _SAFE_ERROR_CODES else 'unknown'
    if isinstance(error, SQLAlchemyError):
        category = 'database'
    elif isinstance(error, ValueError):
        category = 'input'
    elif isinstance(error, RuntimeError):
        category = 'runtime'
    else:
        category = 'unexpected'
    logger.error(
        'DOCUMENT_IMPORT_FAILED mode=%s stage=%s error_type=%s error_code=%s',
        mode, stage, category, code,
    )
