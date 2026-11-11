"""Keep the common priority UI contract in standard regression discovery."""
from pathlib import Path
import shutil
import subprocess
import unittest


class VehiclePriorityPresentationJavascriptTests(unittest.TestCase):
    def test_common_projection_display(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable')
        result = subprocess.run([node, '--test', 'tests/vehicle_priority_presentation_js.cjs'],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
