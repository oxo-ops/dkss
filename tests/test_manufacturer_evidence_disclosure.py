"""Static contracts for the real historical source-gap disclosure interaction.

No browser/application is imported. These checks do not certify visibility;
Chromium must still exercise the exact candidate at all five viewport widths.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = (ROOT / 'tests/video_connected_browser/confirmation_acceptance.py').read_text()
APP = (ROOT / 'static/js/vehicle_karte_analysis_ai.js').read_text()


class ManufacturerEvidenceDisclosureContracts(unittest.TestCase):
    def test_unique_disclosure_and_gap_targets(self):
        self.assertEqual(HARNESS.count("evidence = drawer.locator('details.ka-action-evidence')"), 1)
        self.assertIn("expect(evidence).to_have_count(1)", HARNESS)
        self.assertEqual(HARNESS.count("gap = drawer.locator('p.ka-historical-source-gap')"), 1)

    def test_real_summary_click_precedes_open_visibility_and_viewport_checks(self):
        steps = ["expect(evidence).not_to_have_attribute('open', '')",
                 "evidence.locator(':scope > summary').click()",
                 "expect(evidence).to_have_attribute('open', '')",
                 "gap = drawer.locator('p.ka-historical-source-gap')",
                 "expect(gap).to_be_visible()",
                 'gap.scroll_into_view_if_needed()',
                 'expect(gap).to_be_in_viewport()',
                 "page.screenshot(path=str(out / f'{args.case}-historical-source-gap-{view_width}.png'), full_page=True)"]
        positions = [HARNESS.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(HARNESS.count('expect(gap).to_be_in_viewport()'), 1)

    def test_disclosure_is_not_forced_open_with_script_or_attribute(self):
        section = HARNESS[HARNESS.index("evidence = drawer.locator('details.ka-action-evidence')"):
                          HARNESS.index("drawer.locator('.ka-drawer-close').click()", HARNESS.index("evidence = drawer.locator('details.ka-action-evidence')"))]
        for forbidden in ('evaluate(', 'setAttribute(', 'removeAttribute(', 'dispatch_event(', '.open ='):
            self.assertNotIn(forbidden, section)

    def test_app_keeps_gap_inside_default_closed_evidence_disclosure(self):
        self.assertIn('recordLinks.append(node("p", "ka-historical-source-gap", gap));', APP)
        start = APP.index('const evidence = node("details", "ka-action-evidence");')
        end = APP.index('detail.append(evidence);', start)
        section = APP[start:end]
        self.assertIn('evidence.append(node("summary", "", "根拠・詳しい確認手順を見る"));', section)
        self.assertIn('for (const child of [...detail.childNodes]) if (child !== responseControls) evidenceBody.append(child);', section)
        self.assertIn('evidence.append(evidenceBody);', section)
        self.assertNotIn('evidence.open', section)
        self.assertNotIn('setAttribute', section)

    def test_historical_and_current_guards_are_still_distinct(self):
        for required in ("expect(old_card.locator('.ko-priority')).to_have_text('高')",
                         "expect(current_card.locator('.ko-priority')).to_have_text('高 · 60点')",
                         "expect(page.locator('[data-ko-summary-count]')).to_have_text('2件（前回評価を含む）')",
                         "expect(history).not_to_contain_text('REVISED-SYNTHETIC-ORIGINAL-ONLY')",
                         "expect(drawer.locator('.ka-historical-source-gap')).to_have_count(0)"):
            self.assertIn(required, HARNESS)


if __name__ == '__main__':
    unittest.main()
