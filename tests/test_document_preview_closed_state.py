"""Preserve explicit preview close without changing selected-document behavior."""
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode, parse_qs, urlsplit
import unittest
from jinja2 import Environment

class DocumentPreviewClosedStateTests(unittest.TestCase):
    def macro(self, closed):
        text=(Path(__file__).resolve().parents[1]/'templates/vehicle_karte_documents.html').read_text()
        macro=text[text.index('{% macro document_url'):text.index('{%- endmacro %}')+len('{%- endmacro %}')]
        return Environment().from_string(macro).make_module(dict(
            request=SimpleNamespace(args={'document':'closed'} if closed else {}),
            vehicle=SimpleNamespace(id=7), document_page=SimpleNamespace(per_page=10),
            document_filters=SimpleNamespace(kind='',q='日本語',period='',uploader=''),
            url_for=lambda endpoint,**kw:'/documents?'+urlencode({k:v for k,v in kw.items() if v is not None}))).document_url
    def test_paging_and_type_keep_closed(self):
        url=self.macro(True)
        for kw in ({'page':2},{'kind':'inspection'}):
            q=parse_qs(urlsplit(url(**kw).strip()).query)
            self.assertEqual(q['document'],['closed'])
            self.assertEqual(q['q'],['日本語'])
    def test_explicit_selection_reopens(self):
        q=parse_qs(urlsplit(self.macro(True)(document='document:123').strip()).query)
        self.assertEqual(q['document'],['document:123'])
    def test_default_auto_selection_unchanged(self):
        q=parse_qs(urlsplit(self.macro(False)(page=2).strip()).query)
        self.assertNotIn('document',q)
    def test_filter_form_carries_closed_only(self):
        text=(Path(__file__).resolve().parents[1]/'templates/vehicle_karte_documents.html').read_text()
        self.assertIn("{% if request.args.get('document') == 'closed' %}\n                <input type=\"hidden\" name=\"document\" value=\"closed\">",text)
