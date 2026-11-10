"""Allowlisted SMTP failure metadata; never format provider exception payloads."""
import smtplib
import ssl


def log_email_delivery_failure(logger, *, purpose, stage, error):
    # Both metadata values are internal constants, but fail closed if a future
    # caller passes request/provider data. Exception class names can themselves
    # be untrusted, so only fixed categories are retained.
    purpose = purpose if type(purpose) is str and purpose in ('notification', 'email_change') else 'unknown'
    stage = stage if type(stage) is str and stage in ('connect', 'starttls', 'authenticate', 'send', 'close') else 'unknown'
    if isinstance(error, smtplib.SMTPAuthenticationError):
        category = 'authentication'
    elif isinstance(error, smtplib.SMTPRecipientsRefused):
        category = 'recipient_refused'
    elif isinstance(error, smtplib.SMTPSenderRefused):
        category = 'sender_refused'
    elif isinstance(error, smtplib.SMTPDataError):
        category = 'data_rejected'
    elif isinstance(error, ssl.SSLError):
        category = 'tls'
    elif isinstance(error, smtplib.SMTPServerDisconnected):
        category = 'connection'
    elif isinstance(error, smtplib.SMTPException):
        category = 'smtp'
    elif isinstance(error, OSError):
        category = 'connection'
    else:
        category = 'unexpected'
    logger.error(
        'EMAIL_DELIVERY_FAILED purpose=%s stage=%s error_type=%s',
        purpose, stage, category,
    )
