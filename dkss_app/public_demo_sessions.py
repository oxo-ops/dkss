"""Demo-only active sessions in existing Redis. Missing state always denies access."""
import hashlib
import json
import secrets
import time
import os
import threading

_client_lock = threading.Lock()

def _after_fork():
    global _client_lock
    _client_lock = threading.Lock()

if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)
from flask import abort, current_app, session


def _key(token):
    if not isinstance(token,str) or not 20 <= len(token) <= 128:
        abort(410)
    epoch=str(current_app.config['PUBLIC_DEMO_EPOCH'])
    return 'alseon:demo:active:'+hashlib.sha256((epoch+':'+token).encode()).hexdigest()


def _binding(state):
    return json.dumps({'company':state.get('company_code'),
        'entry_identity':state.get('public_demo_entry_identity'),
        'epoch':current_app.config['PUBLIC_DEMO_EPOCH']},sort_keys=True)


def _store():
    uri=current_app.config['RATELIMIT_STORAGE_URI']
    if current_app.testing and uri == 'memory://':
        return current_app.extensions.setdefault('public_demo_active_sessions',{})
    if not uri.startswith(('redis://','rediss://')):
        abort(503)
    import redis
    # Cache transport only, never the result of GET/SET/DELETE authorization.
    app = current_app._get_current_object()
    identity = (os.getpid(), uri)
    with _client_lock:
        cached = app.extensions.get('public_demo_redis_client')
        if cached is None or cached[0] != identity:
            client = redis.Redis.from_url(uri, socket_connect_timeout=3, socket_timeout=3)
            # Do not disconnect a replaced pool while other requests may use it.
            app.extensions['public_demo_redis_client'] = (identity, client)
            return client
        return cached[1]


def issue(state=None):
    state=session if state is None else state
    token=secrets.token_urlsafe(32)
    provisional=dict(state)
    provisional['public_demo_entry_identity']=state.get('account_identity')
    if not provisional.get('company_code') or not provisional['public_demo_entry_identity']:
        abort(503)
    key=_key(token);store=_store()
    ttl=max(1,int(current_app.config['PUBLIC_DEMO_UNTIL'])-int(time.time()))
    try:
        if isinstance(store,dict):store[key]=_binding(provisional)
        elif not store.set(key,_binding(provisional),ex=ttl,nx=True):abort(503)
    except Exception:
        abort(503)
    # Publish the token to the signed cookie only after the active record exists.
    state['public_demo_entry_identity']=provisional['public_demo_entry_identity']
    state['public_demo_token']=token


def verify():
    key=_key(session.get('public_demo_token'));store=_store()
    try:active=store.get(key)
    except Exception:abort(503)
    if isinstance(active,bytes):
        try:active=active.decode('utf-8')
        except UnicodeDecodeError:active=None
    if not isinstance(active,str) or not secrets.compare_digest(active,_binding(session)):
        session.clear()
        abort(410)


def revoke():
    key=_key(session.get('public_demo_token'));store=_store()
    try:
        if isinstance(store,dict):store.pop(key,None)
        else:
            deleted=store.delete(key)
            if deleted not in (0,1):abort(503)
    except Exception:abort(503)
