"""Contract self-tests use synthetic metrics, not a substitute for Chromium QA."""
from copy import deepcopy
import unittest
from overview_layout_contract import validate_overview_readability


def box(left=25, top=0, width=270, height=18):
    return dict(left=left, top=top, right=left+width, bottom=top+height, width=width, height=height)


def text(value, *, lines=1, bounds=None):
    return dict(text=value, lines=lines, bounds=bounds or box(), visible=True, contained=True, noOverflow=True)


def valid_measurement():
    return dict(viewportWidth=320, rootWidth=296, summary=box(height=80), groups=[
        dict(bounds=box(), label=text('未解消の対応'), count=text('1件')),
        dict(bounds=box(top=25, height=43), label=text('予防整備の提案'), count=text('2件（前回評価を含む）'))],
        workTitle=text('次に必要な対応'), proposalTitle=text('予防整備の提案'),
        costHeader=box(height=62), costTitle=text('直近12か月の整備費用'), costLink=text('費用を見る →'),
        period=text('期間：2025/12/01 ～ 2026/11/12 · 当月を含む12か月（本日まで）',
                    lines=2, bounds=box(top=26, height=36)))


class OverviewReadabilityContractTests(unittest.TestCase):
    def test_expected_narrow_geometry_passes(self):
        for width in (320, 390):
            value = valid_measurement(); value['viewportWidth'] = width
            validate_overview_readability(value)

    def test_expected_wide_geometry_passes(self):
        for width in (768, 1024, 1440):
            value = valid_measurement(); value.update(viewportWidth=width, rootWidth=width-24)
            value['costHeader'] = box(width=width-50)
            value['period']['bounds'] = box(left=230, width=300)
            validate_overview_readability(value)

    def test_one_character_summary_columns_fail(self):
        for index in (0, 1):
            value = valid_measurement(); value['groups'][index]['label']['lines'] = 7
            with self.assertRaisesRegex(AssertionError, 'wraps into 7 lines'):
                validate_overview_readability(value)

    def test_thin_cost_period_fails_even_if_not_overflowing(self):
        value = valid_measurement(); value['period']['bounds'] = box(width=20, height=360)
        with self.assertRaisesRegex(AssertionError, 'narrow text column'):
            validate_overview_readability(value)

    def test_vertical_cost_period_fails(self):
        value = valid_measurement(); value['period']['lines'] = 18
        with self.assertRaisesRegex(AssertionError, 'wraps into 18 lines'):
            validate_overview_readability(value)

    def test_missing_hidden_or_clipped_text_fails(self):
        for change in ({'lines':0}, {'visible':False}, {'contained':False}, {'noOverflow':False}):
            value = valid_measurement(); value['period'].update(change)
            with self.assertRaises(AssertionError): validate_overview_readability(value)

    def test_wrapped_or_clipped_qualifier_fails(self):
        for change in ({'lines':2}, {'contained':False}):
            value = valid_measurement(); value['groups'][1]['count'].update(change)
            with self.assertRaises(AssertionError): validate_overview_readability(value)

    def test_changed_label_or_missing_group_fails(self):
        value = valid_measurement(); value['groups'][1]['label']['text'] = '提案'
        with self.assertRaises(AssertionError): validate_overview_readability(value)
        value = valid_measurement(); value['groups'].pop()
        with self.assertRaises(AssertionError): validate_overview_readability(value)

    def test_narrow_period_must_be_full_width_below_title(self):
        for bounds in (box(width=240, top=26), box(top=10)):
            value = valid_measurement(); value['period']['bounds'] = bounds
            with self.assertRaises(AssertionError): validate_overview_readability(value)

    def test_does_not_modify_metrics(self):
        value = valid_measurement(); before = deepcopy(value)
        validate_overview_readability(value)
        self.assertEqual(value, before)
