"""Synthetic business-clock contract; not a production freshness override."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import time
import unittest
from zoneinfo import ZoneInfo
from time_machine import travel

sys.path.insert(0, str(Path(__file__).resolve().parent))
from confirmation_acceptance import Fixture, exercise_http


class ConfirmationClockContract(unittest.TestCase):
    def test_same_date_acceptance_and_next_date_stale_are_distinct(self):
        # Use today's synthetic date, immediately before Tokyo midnight. Frozen
        # wall time permits the full real flow without a hidden calendar race.
        stamp = datetime.now(ZoneInfo('Asia/Tokyo')).replace(
            hour=23, minute=59, second=59, microsecond=0)
        report = {'requests': [], 'cases': []}
        fixture = Fixture('confirmation_manufacturer', report)
        with travel(stamp, tick=False) as clock:
            try:
                fixture.start()
                start = time.monotonic()
                before = datetime.now(timezone.utc)
                time.sleep(0.01)
                self.assertGreater(time.monotonic(), start)
                self.assertEqual(datetime.now(timezone.utc), before)
                exercise_http(fixture)
                # exercise_http finishes with a new confirmation. Regenerate
                # that input before testing the independent midnight transition.
                fresh = fixture.generate()
                self.assertTrue(fresh['is_current'])
                clock.shift(timedelta(seconds=2))
                stale = fixture.read_result()
                self.assertEqual(stale['status'], 'completed')
                self.assertFalse(stale['is_current'])
                self.assertEqual(stale['generated_at'], fresh['generated_at'])
                fixture.protected()
            finally:
                fixture.close()
