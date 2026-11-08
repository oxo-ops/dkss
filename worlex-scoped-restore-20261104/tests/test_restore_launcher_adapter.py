import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from inspect_observation import Observation
from launcher_adapter import begin_attempt, persist_stage, safe_stage_output

class LauncherAdapterTests(unittest.TestCase):
    def test_safe_observation_roundtrip_persisted_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = Observation(Path(tmp))
            try:
                with obs.scope('snapshot'):
                    raise RuntimeError('SECRET SQL PASSWORD ROW')
            except RuntimeError:
                pass
            parsed = {'status': 'FAILED_OR_COMMIT_UNCERTAIN', 'observation': obs.value,
                      'stderr': 'SECRET', 'sql': 'SECRET', 'url': 'SECRET'}
            record = persist_stage(tmp, parsed, stage='inspect', exit_code=3)
            self.assertEqual(record['safe_output']['observation'], obs.value)
            self.assertNotIn('SECRET', json.dumps(record))
            self.assertEqual(record, json.loads((Path(tmp)/'inspect-finished.json').read_text()))
            parsed['observation']['phase'] = 'SECRET'
            self.assertNotEqual(record['safe_output']['observation'], parsed['observation'])

    def test_unknown_observation_fields_and_missing_observation_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = Observation(Path(tmp)); value = dict(obs.value, raw_exception='SECRET')
            with self.assertRaises(ValueError): safe_stage_output({'observation': value})
            for field in ('status','reason','error_type'):
                self.assertNotIn(field, safe_stage_output({field:'secret.example.com'}))
            with self.assertRaises(ValueError): persist_stage(tmp, {}, stage='inspect', exit_code=0)

    def test_exclusive_result_and_failed_persistence_stop_progression(self):
        with tempfile.TemporaryDirectory() as tmp:
            parsed = {'observation': Observation(Path(tmp)).value}
            persist_stage(tmp, parsed, stage='inspect', exit_code=0)
            with self.assertRaises(FileExistsError): persist_stage(tmp, parsed, stage='inspect', exit_code=0)
        with tempfile.TemporaryDirectory() as tmp:
            parsed = {'observation': Observation(Path(tmp)).value}
            with patch('launcher_adapter.os.fsync', side_effect=OSError('SECRET')):
                with self.assertRaises(OSError): persist_stage(tmp, parsed, stage='inspect', exit_code=0)

    def test_new_attempt_requires_immediate_stop_active_inputs_and_unique_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = dict(attempt_id='a'*32, prior_result={'status':'STOPPED_NO_RETRY',
                'restore_attempted':False,'automatic_retry':False}, active_hashes={'core':'a'*64},
                expected_hashes={'core':'a'*64}, archive_hash='b'*64, expected_archive_hash='b'*64,
                target_hash='c'*64, expected_target_hash='c'*64)
            path = begin_attempt(tmp, **args); self.assertEqual(list(path.iterdir()), [])
            with self.assertRaises(FileExistsError): begin_attempt(tmp, **args)
            for change in ({'prior_result':{}}, {'active_hashes':{}}, {'archive_hash':'d'*64},
                           {'target_hash':'d'*64}, {'attempt_id':'../old'}):
                with self.subTest(change=change), self.assertRaises(ValueError): begin_attempt(tmp, **{**args, **change})
