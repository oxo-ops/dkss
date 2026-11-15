"""Experimental pure wrapper; no IO, scheduling, network, notification or DB.
A caller must atomically persist the ENTIRE returned bundle, never separate parts.
Not wired to production. Existing ledger format/source remains unchanged.
"""
import copy
import log_ledger as ledger

FORMAT = 'q09-collection-history-v1'
MAX_HISTORY = 1000

def invalid():
    raise ValueError('INVALID_COLLECTION_HISTORY') from None

def integer(v):
    return type(v) is int and 0 <= v <= ledger.MAX_COUNT

def entry(scan, run):
    return {'run': run, 'window': copy.deepcopy(scan['window']),
            'response': scan['last_response_status'],
            'coverage': 'unverified',
            'diagnostics': copy.deepcopy(scan['counts'])}

def validate(bundle, resource):
    try:
        ledger.exact_keys(bundle, {'format','ledger','prior_runs_without_history','history'})
        if bundle['format'] != FORMAT:
            invalid()
        ledger.validate_state(bundle['ledger'], resource)
        prior = bundle['prior_runs_without_history']
        history = bundle['history']
        if not integer(prior) or not isinstance(history,list) or len(history)>MAX_HISTORY:
            invalid()
        if bundle['ledger']['runs'] != prior + len(history):
            invalid()
        for i,item in enumerate(history,prior+1):
            ledger.exact_keys(item, {'run','window','response','coverage','diagnostics'})
            if type(item['run']) is not int or item['run'] != i:
                invalid()
            if ledger.window(item['window']) != item['window']:
                invalid()
            if item['response'] not in {'not_observed','page','api_failure','invalid_page'} or item['coverage'] != 'unverified':
                invalid()
            counts=item['diagnostics']
            if not isinstance(counts,dict) or counts.keys()-ledger.DIAGNOSTICS or any(not integer(n) for n in counts.values()):
                invalid()
        if history and history[-1] != entry(bundle['ledger']['last_scan'], bundle['ledger']['runs']):
            invalid()
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        invalid()

def wrap_existing(state, resource):
    """Preserve legacy runs; explicitly report history not retroactively recoverable."""
    ledger.validate_state(state,resource)
    bundle={'format':FORMAT,'ledger':copy.deepcopy(state),
            'prior_runs_without_history':state['runs'],'history':[]}
    validate(bundle,resource)
    return bundle

def observe(bundle, transcript):
    resource=transcript.get('resource') if isinstance(transcript,dict) else None
    validate(bundle,resource)
    if len(bundle['history'])>=MAX_HISTORY:
        # Never silently evict unresolved windows, nor observe without recording.
        raise ValueError('COLLECTION_HISTORY_FULL') from None
    state, report=ledger.observe(bundle['ledger'],transcript)
    output=copy.deepcopy(bundle)
    output['ledger']=state
    output['history'].append(entry(report['scan'],state['runs']))
    validate(output,resource)
    return output, report

def summary(bundle, resource):
    validate(bundle,resource)
    return {'recorded_runs':len(bundle['history']),
            'prior_runs_without_history':bundle['prior_runs_without_history'],
            'response_failure_runs':sum(e['response'] in {'api_failure','invalid_page'} for e in bundle['history']),
            'unverified_runs':len(bundle['history']),
            'coverage':'unverified', 'delivery':'not_attempted', 'scheduled':False}
