"""Seed signed test sessions with the real account generation, as login now does."""
def identity_for(company_code, username, app=None):
    from flask import current_app
    from dkss_app.models import User
    app = app or current_app._get_current_object()
    with app.app_context():
        row = User.query.filter_by(company_code=company_code, username=username).first()
        return row.account_identity if row else None
