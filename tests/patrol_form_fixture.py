"""Fresh patrol forms for existing callers; explicit stale proofs stay intact."""
import re


def fresh_patrol_data(client, path, data):
    if not isinstance(data, dict) or 'person_selection_token' in data:
        return data
    if not re.fullmatch(r'/pointouts/(new|\d+/edit)', path):
        return data
    if not data.get('target_user') or (path == '/pointouts/new' and data.get('target_type') != 'user'):
        return data
    # These old fixtures mean a fresh selection. An extra GET would execute a
    # Driver SELECT inside Q04's POST SQL gate and move the measured race.
    # Match identity_fixture.PersonSelectionClient without altering the gate.
    from flask import session
    from dkss_app.person_selection import issue
    with client.session_transaction() as browser_session:
        claims = dict(browser_session)
    with client.application.test_request_context():
        session.update(claims)
        proof = issue()
    return dict(data, person_selection_token=proof)
