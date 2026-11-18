"""Presentation contract: video rows retain exact record links and data."""
import pathlib
import unittest
from jinja2 import Environment

ROOT = pathlib.Path(__file__).resolve().parents[1]
class VideoProposalListTests(unittest.TestCase):
    def test_dashboard_list_retains_all_items_and_deep_links(self):
        text = (ROOT/'templates/index.html').read_text()
        macro = text[text.index('{% macro attention_table'):text.index('{% endmacro %}',text.index('{% macro attention_table'))+len('{% endmacro %}')]
        render = Environment(autoescape=True).from_string(macro).module.attention_table
        items=[dict(url='/vehicle/karte/647/analysis',proposal_id='saved-1',priority='高',vehicle_number='TEST 101',target='<script>bad</script>',title='Title',action='Confirm only')]
        html=render(items)
        self.assertIn('#proposal=saved-1',html)
        self.assertIn('対応優先度：高',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>',html)
        self.assertIn('Confirm only',html)
        self.assertNotIn('<table',html)
    def test_detail_still_contains_state_risk_timing_and_actions(self):
        text=(ROOT/'static/js/vehicle_karte_analysis_ai.js').read_text()
        for fragment in ['recommendationState(item)', 'recommendationConcern(item)', 'recommendedAction(item)', 'priorityPresentation.details(document, item, sources', 'referenceDrawer.replaceChildren(header, summary, content)', 'controls[index].find']:
            self.assertIn(fragment,text)
        self.assertIn('"ka-video-proposals"',text)
        self.assertNotIn('const grid = node("table", "ka7-proposal-table")',text)
