"""Include the read-only preview UI contract in standard Python discovery."""
from pathlib import Path
import shutil
import subprocess
import unittest


class VehiclePriorityPreviewJavascriptTests(unittest.TestCase):
    def test_node_preview_contract_and_readonly_behavior(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable')
        result = subprocess.run([node, '--test', 'tests/vehicle_priority_preview_js.cjs'],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
