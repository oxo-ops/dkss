import copy
import json
import unittest

import log_ledger as ledger
from render_read_adapter import RenderReadAdapter, AdapterError, page_from_result
from test_log_ledger import row, SERVICE, A, B, C, CANARY

WORKSPACE = 'tea-synthetic12345678'


def result(rows=(), more=False, **extra):
    return {'isError': False, 'content': [{'type': 'text', 'text': json.dumps(
        dict(logs=list(rows), hasMore=more, **extra))}], 'structuredContent': None}


class AdapterTests(unittest.TestCase):
    def run_adapter(self, responses, **kwargs):
        self.calls = []
        def fetch(**query):
            self.calls.append(copy.deepcopy(query))
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return RenderReadAdapter(fetch, workspace=WORKSPACE, resource=SERVICE,
                                 **kwargs).collect(start=A, end=C)

    def test_five_markers(self):
        from log_event_receipts import EVENT_FIELDS
        rows = [row(str(i), B, event + ' ' + ' '.join(
            key + '=' + sorted(values)[0] for key, values in fields.items()) + ' ' + CANARY)
            for i, (event, fields) in enumerate(EVENT_FIELDS.items())]
        output = self.run_adapter([result(rows)])
        self.assertEqual(output['report']['total_marker_or_review_records'], 5)
        self.assertNotIn(CANARY, json.dumps(output))
        self.assertNotIn(SERVICE, json.dumps(output))
        self.assertIsNone(output['report']['read_checkpoint'])
        self.assertFalse(output['sent'])
        self.assertEqual(set(self.calls[0]), {'workspaceId', 'resource', 'type',
                                            'direction', 'startTime', 'endTime', 'limit'})
        self.assertEqual(self.calls[0]['workspaceId'], WORKSPACE)

    def test_pages_and_duplicate(self):
        output = self.run_adapter([result([row()], True, nextStartTime=B, nextEndTime=C), result([row()])])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1]['startTime'], ledger.canonical_time(B))
        self.assertEqual(output['report']['total_unique_log_ids'], 1)
        self.assertEqual(output['adapter_stop'], 'terminal_observed')

    def test_failed_second_read_keeps_first_sanitized(self):
        output = self.run_adapter([result([row()], True, nextStartTime=B, nextEndTime=C), RuntimeError(CANARY)])
        self.assertEqual(output['adapter_stop'], 'read_failed_or_invalid')
        self.assertEqual(output['report']['total_unique_log_ids'], 1)
        self.assertNotIn(CANARY, json.dumps(output))
        self.assertEqual(output['report']['scan']['chain_status'], 'broken')

    def test_error_result(self):
        for value in ({'isError': True, 'content': [{'type': 'text', 'text': CANARY}]},
                      {'isError': False, 'content': [{'type': 'text', 'text': CANARY}]},
                      {'isError': False, 'structuredContent': {'logs': [], 'hasMore': 'false'}}):
            with self.subTest(value=list(value)):
                output = self.run_adapter([value])
                self.assertEqual(output['adapter_stop'], 'read_failed_or_invalid')
                self.assertNotIn(CANARY, json.dumps(output))

    def test_stalled_cursor_never_retried(self):
        output = self.run_adapter([result([], True, nextStartTime=A, nextEndTime=C)])
        self.assertEqual(output['adapter_stop'], 'invalid_chain')
        self.assertEqual(len(self.calls), 1)

    def test_page_bound(self):
        output = self.run_adapter([result([], True, nextStartTime=B, nextEndTime=C)], max_pages=1)
        self.assertEqual(output['adapter_stop'], 'page_budget')
        self.assertEqual(output['report']['scan']['chain_status'], 'incomplete')

    def test_wrong_resource_is_rejected_not_exported(self):
        other = row(); other['labels'][0]['value'] = 'srv-wrong1234567890'
        output = self.run_adapter([result([other])])
        self.assertEqual(output['report']['total_unique_log_ids'], 0)
        self.assertEqual(output['report']['scan']['counts']['rejected_record'], 1)

    def test_structured_shape_and_duplicate_json(self):
        self.assertEqual(page_from_result({'isError': False, 'structuredContent': {'logs': [], 'hasMore': False}})['logs'], [])
        with self.assertRaisesRegex(AdapterError, '^RENDER_REPLY_INVALID$'):
            page_from_result({'isError': False, 'content': [{'type': 'text', 'text': '{"logs":[],"hasMore":false,"hasMore":true}'}]})

    def test_invalid_state_before_read(self):
        def never(**kwargs):
            self.fail('remote access before validation')
        adapter = RenderReadAdapter(never, workspace=WORKSPACE, resource=SERVICE)
        with self.assertRaises(ValueError):
            adapter.collect(start=A, end=C, state={})

    def test_capacity_and_scope(self):
        for kwargs in ({'page_limit': 0}, {'max_pages': 0}, {'page_limit': True}):
            with self.assertRaises(AdapterError):
                RenderReadAdapter(lambda **kw: None, workspace=WORKSPACE, resource=SERVICE, **kwargs)
        huge = {'isError': False, 'structuredContent': {'logs': [], 'hasMore': False, 'secret': CANARY}}
        output = self.run_adapter([huge])
        self.assertEqual(output['adapter_stop'], 'read_failed_or_invalid')


if __name__ == '__main__':
    unittest.main()
