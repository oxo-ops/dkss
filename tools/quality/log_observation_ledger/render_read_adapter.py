"""Bounded read-only Render connector adapter. No credential, schedule or send.

The injected callable must be the existing authorized Render list_logs tool.
Do not inject an untrusted source: matching shapes are not provider authentication.
Raw replies stay transient and must never be printed, serialized or attached.
"""
import copy
import json
import re

import log_ledger as ledger


class AdapterError(ValueError):
    pass


def page_from_result(result):
    """Accept the observed MCP JSON-text reply, or structured JSON; fail closed."""
    try:
        if not isinstance(result, dict) or result.get('isError') is not False:
            raise ValueError()
        page = result.get('structuredContent')
        if page is None:
            content = result.get('content')
            if (not isinstance(content, list) or len(content) != 1 or
                    not isinstance(content[0], dict) or content[0].get('type') != 'text'):
                raise ValueError()
            raw = content[0].get('text')
            if not isinstance(raw, str) or len(raw.encode()) > ledger.MAX_INPUT:
                raise ValueError()
            page = ledger.load_json(raw)
        # Also bounds structuredContent, and forbids non-JSON values.
        if len(json.dumps(page, allow_nan=False).encode()) > ledger.MAX_INPUT:
            raise ValueError()
        if (not isinstance(page, dict) or
                not {'logs', 'hasMore'} <= set(page) or
                set(page) - {'logs', 'hasMore', 'nextStartTime', 'nextEndTime'} or
                type(page['hasMore']) is not bool or not isinstance(page['logs'], list)):
            raise ValueError()
        return page
    except Exception:
        raise AdapterError('RENDER_REPLY_INVALID') from None


class RenderReadAdapter:
    def __init__(self, list_logs, *, workspace, resource, page_limit=100, max_pages=10):
        if (not callable(list_logs) or not isinstance(workspace, str) or
                not re.fullmatch(r'tea-[a-z0-9]{8,64}', workspace) or
                not isinstance(resource, str) or not ledger.RESOURCE.fullmatch(resource) or
                type(page_limit) is not int or not 1 <= page_limit <= 1000 or
                type(max_pages) is not int or not 1 <= max_pages <= ledger.MAX_PAGES):
            raise AdapterError('INVALID_READ_CONFIGURATION')
        self._call = list_logs
        self._workspace, self._resource = workspace, resource
        self._limit, self._pages = page_limit, max_pages

    def collect(self, *, start, end, state=None):
        target = ledger.window({'startTime': start, 'endTime': end})
        # Validate before any remote read; never silently reset invalid state.
        original = ledger.new_state(self._resource) if state is None else copy.deepcopy(state)
        ledger.validate_state(original, self._resource)
        transcript = {'resource': self._resource, 'window': target,
                      'direction': 'forward', 'pages': []}
        current = target
        total_bytes = 0
        stop = 'page_budget'
        for _ in range(self._pages):
            query = {'resource': [self._resource], 'type': ['app'],
                     'direction': 'forward', 'startTime': current['startTime'],
                     'endTime': current['endTime'], 'limit': self._limit}
            try:
                result = self._call(workspaceId=self._workspace, **copy.deepcopy(query))
                page = page_from_result(result)
                total_bytes += len(json.dumps(page, allow_nan=False).encode())
                if total_bytes > ledger.MAX_INPUT:
                    raise AdapterError('INPUT_BOUND')
                reply = {'ok': True, 'page': page}
            except Exception:
                # No exception message/class, raw result or routing is returned.
                reply = {'ok': False}
            transcript['pages'].append({'query': query, 'reply': reply})
            candidate, report = ledger.observe(original, transcript)
            scan = report['scan']
            if not reply['ok']:
                stop = 'read_failed_or_invalid'; break
            if scan['chain_status'] == 'broken':
                stop = 'invalid_chain'; break
            if scan['terminal_seen']:
                stop = 'terminal_observed'; break
            current = scan['next_window']
        # Both output objects are sanitized by the original ledger. No outbox or
        # operational persistence is modified; caller must use its own CAS.
        return {'state': candidate, 'report': report, 'adapter_stop': stop,
                'source': 'authorized_render_connector', 'scheduled': False,
                'sent': False}
