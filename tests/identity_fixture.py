"""Seed signed test sessions with the real account generation, as login now does."""

from flask.testing import FlaskClient


class PersonSelectionClient(FlaskClient):
    """Existing route fixtures represent a fresh selection unless supplied.

    Production never uses this client. Explicit stale, empty and forged proofs
    are left untouched; their tests use the actual rendered GET form.
    """
    def open(self, *args, **kwargs):
        data = kwargs.get('data')
        if kwargs.get('method', 'GET').upper() == 'POST' and 'json' not in kwargs and (data is None or hasattr(data, 'keys')):
            if data is None or 'approval_version' not in data:
                from approval_form_fixture import fresh_approval_version
                path = args[0] if args else kwargs.get('path', '')
                version = fresh_approval_version(self, path) if isinstance(path, str) else None
                if version is not None:
                    data = data.copy() if data is not None else {}
                    data['approval_version'] = version
                    kwargs['data'] = data
        if kwargs.get('method', 'GET').upper() == 'POST' and hasattr(data, 'keys') and 'person_selection_token' not in data:
            fields = set(data.keys())
            if any(key.startswith('approval_notify_users_') for key in fields) or fields & {'notify_users','reminder_notify_users','manager_username'} or (data.get('target_type') == 'user'):
                from flask import session
                from dkss_app.person_selection import issue
                with self.session_transaction() as browser_session:
                    claims = dict(browser_session)
                with self.application.test_request_context():
                    session.update(claims)
                    proof = issue()
                data = data.copy()
                data['person_selection_token'] = proof
                kwargs['data'] = data
        return super().open(*args, **kwargs)
def identity_for(company_code, username, app=None):
    from flask import current_app
    from dkss_app.models import User
    app = app or current_app._get_current_object()
    with app.app_context():
        row = User.query.filter_by(company_code=company_code, username=username).first()
        return row.account_identity if row else None
