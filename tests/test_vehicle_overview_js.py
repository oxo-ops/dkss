"""Keep the overview's browser controller in the standard regression suite."""
from pathlib import Path
import shutil
import subprocess
import unittest


class VehicleOverviewJavaScriptTests(unittest.TestCase):
    def test_saved_proposal_list(self):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node.js is required for overview controller tests')
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [node, '--test', 'tests/vehicle_karte_overview_js.cjs'],
            cwd=root, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
