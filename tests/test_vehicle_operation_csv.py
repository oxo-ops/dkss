"""Operation CSV contracts, independent of Flask, a database or AI services."""
import json
import unittest
from decimal import Decimal

from upload_validation import UploadValidationError
from vehicle_operation_csv import (
    normalize_vehicle_operation_plate,
    parse_vehicle_operation_csv_row,
    parse_vehicle_operation_date,
    parse_vehicle_operation_decimal,
    read_vehicle_operation_csv,
)


class VehicleOperationCsvTests(unittest.TestCase):
    def test_utf8_bom_and_cp932_keep_original_values(self):
        source = "日報番号,運行日,車両コード,車両,入庫メータ,走行距離\nR-1,2026/10/23,V1,横浜１００あ１２３４,1000.50,12.30\n"
        for encoding in ("utf-8-sig", "cp932"):
            with self.subTest(encoding=encoding):
                row = read_vehicle_operation_csv(source.encode(encoding))[0]
                self.assertEqual(row["line_number"], 2)
                values = parse_vehicle_operation_csv_row(row["source_row"], row["line_number"])
                self.assertEqual(values["operation_date"], "2026-10-23")
                self.assertEqual(values["arrival_meter"], Decimal("1000.50"))
                self.assertEqual(values["distance"], Decimal("12.30"))
                self.assertEqual(json.loads(values["source_row_json"]), row["source_row"])

    def test_quoted_multiline_values_retain_physical_line_number(self):
        source = '日報番号,運行日,車両コード,備考\n\nR-1,2026-10-23,V1,"1行目\n2行目"\n'
        rows = read_vehicle_operation_csv(source.encode())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["line_number"], 4)
        self.assertEqual(rows[0]["source_row"]["備考"], "1行目\n2行目")

    def test_invalid_encoding_and_nul_are_rejected(self):
        for source in (b"\xff", b"\x00"):
            with self.subTest(source=source):
                with self.assertRaises(UploadValidationError):
                    read_vehicle_operation_csv(source)

    def test_duplicate_and_empty_headers_are_rejected(self):
        for source in ("日報番号,運行日,車両,車両\n", "日報番号,運行日,\n", ""):
            with self.subTest(source=source):
                with self.assertRaises(UploadValidationError):
                    read_vehicle_operation_csv(source.encode())

    def test_required_headers_include_vehicle_code_or_plate(self):
        for source in ("運行日,車両\n2026-10-23,横浜\n",
                       "日報番号,車両コード\nR-1,V1\n",
                       "日報番号,運行日\nR-1,2026-10-23\n"):
            with self.subTest(source=source):
                with self.assertRaises(UploadValidationError):
                    read_vehicle_operation_csv(source.encode())

    def test_bad_column_counts_and_quotes_are_rejected(self):
        header = "日報番号,運行日,車両コード\n"
        for row in ("R-1,2026-10-23\n", "R-1,2026-10-23,V1,extra\n",
                    'R-1,2026-10-23,"unclosed\n'):
            with self.subTest(row=row):
                with self.assertRaises(UploadValidationError):
                    read_vehicle_operation_csv((header + row).encode())

    def test_header_only_or_blank_rows_are_not_data(self):
        with self.assertRaisesRegex(UploadValidationError, "データがありません"):
            read_vehicle_operation_csv("日報番号,運行日,車両\n,,\n\n".encode())

    def test_row_errors_keep_source_line_and_field(self):
        cases = [
            ({"日報番号": "", "運行日": "2026-10-23"}, "日報番号"),
            ({"日報番号": "R-1", "運行日": ""}, "運行日"),
            ({"日報番号": "R-1", "運行日": "2026-02-30"}, "運行日"),
            ({"日報番号": "R-1", "運行日": "2026-10-23", "走行距離": "-1"}, "走行距離"),
            ({"日報番号": "R" * 101, "運行日": "2026-10-23"}, "100文字"),
        ]
        for row, field in cases:
            with self.subTest(row=row):
                with self.assertRaisesRegex(UploadValidationError, "CSVの8行目：.*" + field):
                    parse_vehicle_operation_csv_row(row, 8)

    def test_dates_preserve_supported_date_and_time_formats(self):
        self.assertIsNone(parse_vehicle_operation_date(None, "運行日"))
        self.assertEqual(parse_vehicle_operation_date("2024/02/29", "運行日"), "2024-02-29")
        for value in ("2026/10/23 09:10", "2026-10-23 09:10:00"):
            self.assertEqual(parse_vehicle_operation_date(value, "出庫日時", with_time=True),
                             "2026-10-23 09:10:00")
        with self.assertRaises(UploadValidationError):
            parse_vehicle_operation_date("2026-10-23 09:10", "運行日")

    def test_decimal_accepts_zero_thousands_and_exact_two_places(self):
        self.assertIsNone(parse_vehicle_operation_decimal(" ", "走行距離"))
        self.assertEqual(parse_vehicle_operation_decimal("0", "走行距離"), Decimal("0.00"))
        self.assertEqual(parse_vehicle_operation_decimal("1,234.50", "走行距離"), Decimal("1234.50"))
        self.assertEqual(parse_vehicle_operation_decimal("999999999999.99", "走行距離"),
                         Decimal("999999999999.99"))

    def test_decimal_rejects_invalid_precision_and_nonfinite_values(self):
        for value in ("-1", "NaN", "Infinity", "1e3", "12,34", "1.001", "1000000000000", "+1"):
            with self.subTest(value=value):
                with self.assertRaises(UploadValidationError):
                    parse_vehicle_operation_decimal(value, "走行距離")

    def test_plate_normalization_preserves_letters_and_removes_separators(self):
        self.assertEqual(normalize_vehicle_operation_plate(" 横浜１００ あ １２－３４ "),
                         normalize_vehicle_operation_plate("横浜100あ1234"))
        self.assertEqual(normalize_vehicle_operation_plate("ABC－１２３"), "abc123")
        self.assertEqual(normalize_vehicle_operation_plate(None), "")


if __name__ == "__main__":
    unittest.main()
