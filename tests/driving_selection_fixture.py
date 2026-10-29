"""Fresh choices for legacy driving fixtures; stale tests read actual GET forms."""
from flask import session
from dkss_app.person_selection import issue


def fresh_person_proof(client):
    with client.session_transaction() as browser_session:
        claims = dict(browser_session)
    with client.application.test_request_context():
        session.update(claims)
        return issue()
