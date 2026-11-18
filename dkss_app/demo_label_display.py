"""Exact presentation aliases for two verified legacy demo labels; never writes."""
from flask import current_app, has_request_context, request, session


def _in_demo(company, endpoint):
    # The existing before_request guard authenticates, verifies active demo
    # session/expiry and company before either route can render this text.
    return (has_request_context()
            and request.endpoint == endpoint
            and current_app.config.get('PUBLIC_DEMO_CANDIDATE') is True
            and current_app.config.get('PUBLIC_DEMO_SHARED_COMPANY') is True
            and current_app.config.get('PUBLIC_DEMO_COMPANY') == 'AONAGI'
            and session.get('aonagi_readonly_demo') is True
            and session.get('company_code') == company == 'AONAGI')


def plan_factory(value, *, company, vehicle_id, plan_id, event_id):
    if (_in_demo(company, 'vehicle_karte_history')
            and (vehicle_id, plan_id, event_id) == (649, 8, 8)
            and value == '港南車両サービス（架空）'):
        return '港南車両サービス'
    return value


def approval_label(value, *, company, checklist_id, result_id):
    if (_in_demo(company, 'checklist_result_detail')
            and checklist_id == 13 and result_id in (14, 15, 16, 17)
            and value == '体験用管理者確認'):
        return '管理者確認'
    return value
