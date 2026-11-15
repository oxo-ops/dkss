"""Explicit handover UX; uses existing authentication, never selects an identity.

This does not replace server-side revocation or solve in-flight response races.
"""
import secrets
import re
from flask import session, request, render_template, make_response


def switch_user():
    if request.method == 'POST':
        expected = session.get('handover_nonce')
        supplied = request.form.get('handover_nonce', '')
        if (not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected) or
                not re.fullmatch(r'[0-9a-f]{64}', supplied) or
                not secrets.compare_digest(expected, supplied)):
            response = make_response(render_template('user_handover.html', conflict=True))
        else:
            from .auth import logout
            response = make_response(logout())
    else:
        # Stable until logout/login clears the session. Opening another tab
        # must not invalidate a confirmation already being read by this user.
        if not session.get('handover_nonce'):
            session['handover_nonce'] = secrets.token_hex(32)
        response = make_response(render_template('user_handover.html', conflict=False))
    response.headers['Cache-Control'] = 'no-store'
    return response
