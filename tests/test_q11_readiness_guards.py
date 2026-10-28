"""Refuse unknown bootstrap code before executing it or opening a cluster."""
from pathlib import Path
import tempfile
import unittest

from tools.q11_pg_readiness import bootstrap


class ReadinessBootstrapGuards(unittest.TestCase):
    def test_unknown_bootstrap_is_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed"
            candidate = root / "bootstrap.py"
            candidate.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unmodified PR #278"):
                bootstrap(candidate)
            self.assertFalse(marker.exists())

    def test_missing_bootstrap_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                bootstrap(Path(directory) / "missing.py")


if __name__ == "__main__":
    unittest.main()
