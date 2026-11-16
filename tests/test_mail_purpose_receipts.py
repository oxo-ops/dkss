"""Offline enum compatibility only; synthetic log records, no app or transport."""
import importlib.util
import json
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "tools/quality/log_observation_ledger/log_event_receipts.py"
SPEC = importlib.util.spec_from_file_location("mail_purpose_receipts", PATH)
receipts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receipts)


class MailPurposeReceipts(unittest.TestCase):
    def project(self, purpose, stage="send"):
        service = "srv-synthetic12345678"
        return receipts.project_page({"hasMore": False, "logs": [{
            "id": "synthetic-log-1", "timestamp": "2026-11-16T00:00:00Z",
            "labels": [{"name": "resource", "value": service}, {"name": "type", "value": "app"}],
            "message": f"EMAIL_DELIVERY_FAILED purpose={purpose} stage={stage} error_type=connection"
        }]}, service)

    def test_mfa_stages_retain_failure_details(self):
        for stage in ("connect", "starttls", "authenticate", "send", "close"):
            value = self.project("mfa", stage)["receipts"][0]
            self.assertEqual(value["details"], {"purpose": "mfa", "stage": stage, "error_type": "connection"})
            self.assertFalse(value["requires_review"])
            self.assertEqual(value["notification_status"], "not_sent")

    def test_existing_purposes_and_coverage_limits_preserved(self):
        for purpose in ("notification", "email_change", "unknown"):
            result = self.project(purpose)
            self.assertEqual(result["receipts"][0]["details"]["purpose"], purpose)
            self.assertFalse(result["receipts"][0]["requires_review"])
            self.assertTrue(result["coverage_requires_review"])
            self.assertEqual(result["delivery_status"], "not_attempted")

    def test_unknown_purpose_is_not_exported_or_trusted(self):
        result = self.project("PRIVATE-CANARY")
        self.assertNotIn("PRIVATE-CANARY", json.dumps(result))
        self.assertTrue(result["receipts"][0]["requires_review"])
        self.assertEqual(result["receipts"][0]["details"]["purpose"], "unverified")
