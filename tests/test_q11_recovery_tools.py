"""Q11 detector and isolation regressions; no server or external service required."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.q11_recovery import Cluster, Drill, compare_snapshots, verify_files


class RecoveryToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / "uploads/Q11A/a.pdf"
        self.file.parent.mkdir(parents=True)
        self.file.write_bytes(b"synthetic-Q11")
        self.manifest = [dict(key="uploads/Q11A/a.pdf", size=13,
                              sha256=hashlib.sha256(b"synthetic-Q11").hexdigest())]

    def test_success_reports_actual_hash_and_size(self):
        result = verify_files(self.root, self.manifest)
        self.assertEqual((result["status"], result["checked"], result["matched"]), ("passed", 1, 1))
        self.assertEqual(result["files"][0]["actual_sha256"], self.manifest[0]["sha256"])
        self.assertGreaterEqual(result["duration_seconds"], 0)

    def test_same_size_tamper_is_detected(self):
        self.file.write_bytes(b"Synthetic-Q11")
        result = verify_files(self.root, self.manifest)
        self.assertEqual(result["files"][0]["status"], "mismatch")
        self.assertEqual(result["matched"], 0)

    def test_missing_is_reported_without_rebaselining(self):
        self.file.unlink()
        before = json.dumps(self.manifest)
        self.assertEqual(verify_files(self.root, self.manifest)["files"][0]["status"], "missing")
        self.assertEqual(json.dumps(self.manifest), before)

    def test_manifest_validation(self):
        for field, value in (("key", "../escape"), ("key", "/absolute"),
                             ("key", "a//b"), ("key", "a/./b"), ("key", "C:a"),
                             ("key", "a\\b"), ("key", 3), ("size", True),
                             ("size", -1), ("sha256", "0"), ("sha256", 3)):
            with self.subTest(field=field, value=value):
                row = dict(self.manifest[0], **{field: value})
                with self.assertRaises(ValueError): verify_files(self.root, [row])
        for rows in ([], {}, [None], self.manifest * 2):
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError): verify_files(self.root, rows)

    def test_snapshot_detects_count_content_sequence_and_schema_changes(self):
        before = dict(tables={"t": dict(count=1, sha256="a")}, sequences={"s": [1, True]}, schema={"triggers": ["trigger"]})
        self.assertEqual(compare_snapshots(before, copy.deepcopy(before)), [])
        for category, key, value in (("tables", "t", dict(count=0, sha256="b")),
                                      ("tables", "t", dict(count=1, sha256="b")),
                                      ("sequences", "s", [1, False]), ("schema", "triggers", [])):
            after = copy.deepcopy(before)
            after[category][key] = value
            self.assertEqual(compare_snapshots(before, after)[0]["category"], category)

    def test_existing_directory_refused_before_commands(self):
        with patch("tools.q11_recovery.subprocess.run") as command:
            with self.assertRaises(FileExistsError): Cluster("unused", self.root)
            command.assert_not_called()

    def test_inherited_pg_configuration_removed(self):
        with patch.dict("os.environ", {"PGSERVICE": "production", "PGHOST": "remote", "PGOPTIONS": "unsafe"}):
            cluster = Cluster("unused", self.root / "new-cluster")
        self.assertEqual(cluster.env["PGHOST"], "127.0.0.1")
        self.assertNotIn("PGSERVICE", cluster.env)
        self.assertNotIn("PGOPTIONS", cluster.env)

    def test_failed_case_writes_failure_evidence(self):
        cluster = type("OwnedFixture", (), {"work": self.root})()
        drill = Drill(cluster)
        def fail():
            raise RuntimeError("injected failure")
        with self.assertRaises(RuntimeError):
            drill.case("injected", fail)
        result = json.loads((self.root / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(result["cases"][0]["status"], "failed")
        self.assertIn("injected failure", result["cases"][0]["error"])


if __name__ == "__main__":
    unittest.main()
