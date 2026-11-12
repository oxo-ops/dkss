"""Synthetic-only pseudonymous transcript -> original ledger -> private CAS.
No provider calls, notification, operational path, or automatic initialization.
"""
import copy
import json
import log_ledger as ledger

# Do not use SyntheticFileCASStore: its bundle is pinned to its own fake resource.
# This function prepares a single versioned payload for an injected private store.
def integrate(snapshot, transcript):
    if (not isinstance(snapshot, dict) or set(snapshot) != {'format', 'revision', 'ledger'} or
            snapshot['format'] != 'q09-pseudonymous-bridge-trial-v1' or
            type(snapshot['revision']) is not int or snapshot['revision'] < 0 or
            not isinstance(snapshot['ledger'], dict)):
        raise ValueError('INVALID_BRIDGE_STATE')
    state, report = ledger.observe(snapshot['ledger'], transcript)
    return {'format': snapshot['format'], 'revision': snapshot['revision']+1, 'ledger': state}, report


def commit_once(store, transcript):
    # Store must supply a version independent of application revision.
    version, snapshot = store.read()
    candidate, report = integrate(snapshot, transcript)
    # No retries and no send even after acknowledged persistence.
    store.replace(expected_version=version, payload=candidate)
    return report
