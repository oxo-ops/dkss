"""Static and pure-JS observation contracts. No app, sockets, or browser."""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

HERE = Path(__file__).resolve().parent
BASE = HERE / 'video_connected_browser/acceptance.py'
SOURCE = HERE.parent
TEXT = BASE.read_text()
TREE = ast.parse(TEXT)


class PreviewContracts(unittest.TestCase):
    def test_diagnostic_is_separate_1440_only_and_has_no_receiver_or_download(self):
        branches = [n for n in ast.walk(TREE) if isinstance(n, ast.If)
                    and ast.unparse(n.test) == 'args.invoice_preview_observe_only']
        branch = next(n for n in branches if any(isinstance(x, ast.Return) for x in n.body))
        text = ast.unparse(branch)
        self.assertIn('PREVIEW_DIAGNOSTIC_COMPLETE_NOT_ACCEPTANCE', text)
        self.assertIn('browser_acceptance_passed=False', text)
        self.assertIn('native_download_reexecuted=False', text)
        self.assertIn('full_invoice_browser_executed=False', text)
        self.assertEqual(text.count('observe_invoice_preview(1440,'), 2)
        self.assertNotIn('ExactInvoiceDownload', text)
        self.assertNotIn('expect_download', text)
        self.assertNotIn('pdf.begin', text)
        self.assertIn('snapshot() == before', text)

    def test_header_filter_excludes_cookies_and_authorization(self):
        function = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'selected_headers')
        namespace = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<pure header observer>', 'exec'), namespace)
        result = namespace['selected_headers']({'Content-Length': '470', 'Cookie': 'not copied',
            'Authorization': 'not copied', 'Range': 'bytes=0-469'}, ('content-length', 'range', 'accept-ranges'))
        self.assertEqual(result, {'content-length': '470', 'range': 'bytes=0-469', 'accept-ranges': None})
        self.assertNotIn('not copied', json.dumps(result))

    def test_preview_terminal_state_requires_real_page_and_raster(self):
        state = next(ast.literal_eval(n.value) for n in TREE.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'PREVIEW_STATE' for t in n.targets))
        program = '''const state = (STATE);
let mode = 'ready';
globalThis.document = {querySelector() {
  if (mode === 'missing') return null;
  return {dataset:{pdfError:mode==='error'?'true':undefined,sourceBase:'/source',requestedRecordKey:'maintenance_1'},
    querySelector(sel){return {'[data-pdf-count]':{textContent:'1'},'[data-pdf-page]':{value:'1'},
      '[data-pdf-status]':{textContent:mode==='loading'?'原本を読み込み中…':'スクロールでページ移動'}}[sel]},
    querySelectorAll(sel){return sel.endsWith(' canvas')?(mode==='no-raster'?[]:[{width:100,height:200}]):
      [{style:{width:mode==='zero-size'?'0px':'100px',height:'200px'}}]},closest(){return {open:true}}};
}};
const results={};for(mode of ['ready','missing','error','loading','no-raster','zero-size'])results[mode]=state();
process.stdout.write(JSON.stringify(results));'''.replace('STATE', state)
        result = subprocess.run(['node', '-e', program], check=True, capture_output=True, text=True)
        values = json.loads(result.stdout)
        self.assertTrue(values['ready']['ready'])
        for mode in ('missing', 'error', 'loading', 'no-raster', 'zero-size'):
            self.assertFalse(values[mode]['ready'], mode)
        self.assertTrue(values['error']['error'])

    def test_frozen_pdfjs_470_byte_fixture_cannot_enable_range(self):
        vendor = (SOURCE / 'static/vendor/pdfjs/pdf.mjs').read_text()
        start = vendor.index('function validateRangeRequestCapabilities(')
        function = vendor[start:vendor.index('function extractFilenameFromHeader(', start)]
        program = function + '''
const results=[];
for(const length of [null,'470','131072','131073']){
const values={'Content-Length':length,'Accept-Ranges':'bytes','Content-Encoding':'identity'};
results.push(validateRangeRequestCapabilities({responseHeaders:{get:k=>values[k]},
isHttp:true,rangeChunkSize:2**16,disableRange:false}));}
process.stdout.write(JSON.stringify(results));'''
        values = json.loads(subprocess.run(['node', '-e', program], check=True, capture_output=True, text=True).stdout)
        self.assertEqual([x['isRangeSupported'] for x in values], [False, False, False, True])

    def test_verified_receiver_and_native_modules_are_unchanged(self):
        for path, expected in ((BASE.parent / 'exact_invoice_download.py','e84e269a1f72e9772bd33284024601f31644d1c0'),
                              (HERE / 'video_connected_browser/native_pdf_navigation.py',
                               '4573aa6f07666f1d4e508b7352cc4cd42df0a323')):
            data = path.read_bytes()
            self.assertEqual(hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest(), expected)
        for forbidden in ('route.continue_', 'route.fallback', 'Fetch.enable', 'Network.enable'):
            self.assertNotIn(forbidden, TEXT)


if __name__ == '__main__':
    unittest.main()
