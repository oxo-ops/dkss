"""Bound exponent expansion without dropping original OCR candidates."""
import copy
import unittest
from unittest.mock import patch

from driving_report_validation import _number, prepare_candidates


class NumericExpansionTests(unittest.TestCase):
    def test_existing_numeric_spellings_remain_exact(self):
        for raw, expected in [('1e2', '100'), ('1.2300', '1.2300'),
                              ('1e-3', '0.001'), ('-0.00', '-0.00'),
                              ('１２,３４５.６７', '12345.67')]:
            with self.subTest(raw=raw):
                self.assertEqual(_number(raw), expected)
        self.assertEqual(_number('1,234.50 km', mileage=True), '1234.50')

    def test_exact_generic_output_boundaries(self):
        self.assertEqual(len(_number('1e-98')), 100)
        self.assertEqual(len(_number('-1e-97')), 100)
        for raw in ['1e-99', '-1e-98', '0e-99']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                _number(raw)

    def test_distance_zero_scale_boundary(self):
        self.assertEqual(len(_number('0e-48', mileage=True)), 50)
        with self.assertRaises(ValueError):
            _number('0e-49', mileage=True)

    def test_extreme_exponents_rejected_before_format(self):
        # A tiny input must not allocate gigabytes even for zero; positive
        # nonzero exponents are checked before a decimal comparison as well.
        for raw in ['1e-1000000000', '0e-1000000000', '-0e-1000000000',
                    '1e1000000000']:
            with self.subTest(raw=raw), patch('driving_report_validation.format',
                    create=True, side_effect=AssertionError('format called')):
                with self.assertRaises(ValueError):
                    _number(raw)

    def test_oversized_candidates_kept_out_of_typed_fields(self):
        raw = '1e-1000000000'
        for collection in ['report_items', 'events', 'duties', 'extra_items']:
            row = {'source_pages': [1], collection: [
                {'source_page': 1, 'item_name': 'fuel', 'value': raw,
                 'numerator': raw, 'denominator': raw, 'status': 'candidate'}]}
            original = copy.deepcopy(row)
            prepare_candidates({'records': [row]}, 1, {}, {},
                               ('report_items', 'events', 'duties', 'extra_items'))
            for key in ['value', 'numerator', 'denominator']:
                self.assertIsNone(row[collection][0][key])
            self.assertEqual(row[collection][0]['status'], 'unknown')
            self.assertEqual(row['_ocr_raw_candidate'], original)
            issues = [i for i in row['_ocr_issues'] if i['raw'] == raw]
            self.assertEqual(len(issues), 3)
            self.assertTrue(all(i['display'] == raw for i in issues))


if __name__ == '__main__':
    unittest.main()
