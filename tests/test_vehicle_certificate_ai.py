import json
import unittest
from unittest.mock import patch

import vehicle_certificate_ai as ai


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, *args):
        return json.dumps(self.payload).encode("utf-8")


def valid_vehicle():
    vehicle = {key: None for key in ai.FIELDS}
    vehicle.update({
        "plate_area": "品川",
        "plate_class": "010",
        "plate_kana": "あ",
        "plate_number": "0012",
        "chassis_number": "SH1EDD-100025",
        "model_code": "QPG-SH1EDDG",
        "manufacturer": "日野",
        "first_registration_date": "2020-04-01",
        "gross_vehicle_weight": "24950",
        "max_payload": "12000",
        "inspection_expiry": "2027-07-10",
    })
    return vehicle


class VehicleCertificateAITests(unittest.TestCase):

    def test_valid_vehicle(self):
        vehicle = valid_vehicle()
        self.assertEqual(ai._validate({
            "vehicle": vehicle,
            "warnings": [],
        }), vehicle)

    def test_leading_zeros_preserved(self):
        vehicle = valid_vehicle()
        result = ai._validate({
            "vehicle": vehicle,
            "warnings": [],
        })
        self.assertEqual(result["plate_class"], "010")
        self.assertEqual(result["plate_number"], "0012")

    def test_invalid_date_rejected(self):
        vehicle = valid_vehicle()
        vehicle["inspection_expiry"] = "2026-02-30"
        with self.assertRaises(ValueError):
            ai._validate({
                "vehicle": vehicle,
                "warnings": [],
            })

    def test_invalid_weight_rejected(self):
        vehicle = valid_vehicle()
        vehicle["gross_vehicle_weight"] = "24,950kg"
        with self.assertRaises(ValueError):
            ai._validate({
                "vehicle": vehicle,
                "warnings": [],
            })

    def test_missing_fields_rejected(self):
        vehicle = valid_vehicle()
        del vehicle["chassis_number"]
        with self.assertRaises(ValueError):
            ai._validate({
                "vehicle": vehicle,
                "warnings": [],
            })

    def test_empty_file_rejected(self):
        with self.assertRaises(ValueError):
            ai.extract_vehicle_certificate(b"")

    def test_mock_ai_extracts_without_network(self):
        payload = {
            "status": "completed",
            "output": [{
                "content": [{
                    "type": "output_text",
                    "text": json.dumps({
                        "vehicle": valid_vehicle(),
                        "warnings": [],
                    }),
                }],
            }],
        }

        with patch.dict("os.environ", {
            "OPENAI_API_KEY": "test-key",
        }):
            with patch.object(
                ai,
                "prepare_maintenance_invoice_pdf",
                return_value=b"%PDF-1.4 test",
            ):
                with patch.object(
                    ai.urllib.request,
                    "urlopen",
                    return_value=FakeResponse(payload),
                ) as mocked:
                    result = ai.extract_vehicle_certificate(
                        b"%PDF-1.4 test",
                        "sample.pdf",
                    )

        self.assertEqual(
            result["vehicle"]["model_code"],
            "QPG-SH1EDDG",
        )
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["source_filename"], "sample.pdf")
        mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
