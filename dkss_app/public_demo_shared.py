"""Shared synthetic-company mode: retain ordinary company business routes.
Isolated candidate only; enabling external delivery/AI requires separate release review.
"""
from flask import abort, current_app, request


def enabled():
    return current_app.config.get('PUBLIC_DEMO_SHARED_COMPANY') is True


def guard():
    # Business data remains shared. Authentication/account administration is not
    # part of a passwordless synthetic-company trial, and never becomes public.
    if request.path == '/itc' or request.path.startswith('/itc/'):
        abort(403)
    if request.endpoint in {'login', 'mfa', 'register', 'switch_user', 'new_driver', 'edit_driver', 'delete_driver', 'company_registration', 'verify_email_change'}:
        abort(403)
    if request.endpoint == 'settings' and request.method != 'GET':
        abort(403)
    if request.endpoint in {'test_email_notification', 'push_test', 'push_subscribe', 'push_unsubscribe'}:
        abort(403)  # Real delivery/subscription controls await an explicit recipient decision.
    # Normal require_login, CSRF and each handler's company checks run next.
    return None
