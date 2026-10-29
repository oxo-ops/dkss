"""Validate checked-in public display assets against the retained original."""
import importlib.util
from pathlib import Path
import unittest

class NotificationIconTests(unittest.TestCase):
    def test_derivatives_match_original_and_decode(self):
        path = Path(__file__).resolve().parents[1] / "tools/build_notification_icon.py"
        spec = importlib.util.spec_from_file_location("q12_icon", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.build(check=True)
