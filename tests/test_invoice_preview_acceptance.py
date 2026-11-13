"""Pure correlation and regression contracts. No sockets, app, or browser."""
import ast
from collections import Counter
from copy import deepcopy
import hashlib
import json
import subprocess
from pathlib import Path
import unittest
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
BASELINE = json.loads((HERE / 'fixtures/invoice_preview_contract_baseline.json').read_text())
TEXT = (HERE / 'video_connected_browser/acceptance.py').read_text()
TREE = ast.parse(TEXT)
NODES = {node.name: node for node in ast.walk(TREE) if isinstance(node, ast.FunctionDef)}
NS = {'urlsplit': urlsplit}
exec(compile(ast.Module(body=[NODES['require'], NODES['verify_preview_regions'], NODES['verified_preview_fetch']],
                       type_ignores=[]), '<pure classifier>', 'exec'), NS)


def fixture():
    # Replay the actual successful DOM + response observation, with synthetic
    # scope/frame/viewport fields for pure tests only. The old run did NOT prove
    # viewport visibility or record these new frame-identity fields.
    artifact = HERE / 'fixtures/invoice_preview_observation.json'
    report = json.loads(artifact.read_text())
    events = deepcopy(report['invoice_source_events'][:4])
    observation = deepcopy(report['invoice_preview_observations'][0])
    phase = observation['phase']
    observation.update(scope_id=phase, source_event_end=4, canvas_regions_reachable=True, disclosure_closed=True)
    observation['preview_regions'] = region_fixture()
    for event in events:
        event.update(preview_scope_id=phase, same_preview_main_frame=True, frame_url=observation['url'])
    kwargs = dict(source_url=events[0]['url'], source_hash=events[1]['source_sha256'],
        page_url=observation['url'], phase=phase, scope_id=phase, record_key='maintenance_1', console_errors=[])
    return events, observation, kwargs


def region_fixture(width=119, height=169, window_height=200):
    extent = max(window_height, height + 24)
    samples = []
    for edge, scroll_top in [('top', 0), ('bottom', extent-window_height)]:
        top = 12-scroll_top
        clip = dict(left=0,top=0,right=width+24,bottom=window_height)
        paper = dict(left=12,top=top,right=12+width,bottom=top+height,width=width,height=height)
        samples.append(dict(edge=edge,paper=paper,clip=clip,
            region=dict(left=0,top=max(0,-top),right=width,bottom=min(height,window_height-top)),
            viewport=dict(width=width+24,height=window_height),clipping=[],
            raster=dict(width=width,height=height),unobscured=True,stable_samples=7,stable_ms=300,
            scroll=dict(top=scroll_top,left=0,width=width+24,height=window_height,
                extent_width=width+24,extent_height=extent,overflow_y='auto')))
    return samples


class PreviewAcceptance(unittest.TestCase):
    def evaluate(self, values):
        events, observation, kwargs = values
        return NS['verified_preview_fetch'](events, observation, **kwargs)

    def test_exact_aborted_sequence_and_normal_completion(self):
        values = fixture()
        proof = self.evaluate(values)
        self.assertEqual(proof['classification'], 'verified_rendered_preview_fetch')
        self.assertFalse(proof['abort_caller_proven'])
        self.assertEqual(proof['event_sequences'], [1, 2, 3, 4])
        values[0][-1].update(event='requestfinished')
        values[0][-1].pop('failure')
        self.assertEqual(self.evaluate(values)['terminal_event'], 'requestfinished')

    def test_every_request_event_rejects_wrong_identity_frame_phase_url_method_type(self):
        mutations = {
            'request_id': 999, 'url': 'http://elsewhere/source', 'method': 'POST',
            'resource_type': 'document', 'is_navigation_request': True,
            'phase': 'width:1440/original-download', 'preview_scope_id': 'different-scope',
            'same_preview_main_frame': False, 'frame_url': 'http://127.0.0.1:8765/other',
        }
        for index in range(4):
            for key, value in mutations.items():
                with self.subTest(event=index, key=key):
                    values = fixture(); values[0][index][key] = value
                    with self.assertRaises(AssertionError): self.evaluate(values)

    def test_all_unready_error_or_invisible_observations_fail(self):
        mutations = {'width': 900, 'stage': 'history', 'phase': 'wrong', 'scope_id': 'wrong',
            'url': 'wrong', 'ready': False, 'error': True, 'present': False, 'wait_error': 'TimeoutError',
            'total': '0', 'current': '0', 'status': 'loading', 'source_base': '/wrong',
            'record_key': 'maintenance_2', 'disclosure_open': False, 'disclosure_closed': False,
            'canvas_regions_reachable': False, 'source_event_end': 3,
            'raster': [{'width': 0, 'height': 169}], 'dimensions': [{'width': 119, 'height': 0}]}
        for key, value in mutations.items():
            with self.subTest(key=key):
                values = fixture(); values[1][key] = value
                with self.assertRaises(AssertionError): self.evaluate(values)
        for key in ('raster', 'dimensions'):
            for value in ([], [{'width': 1, 'height': 1}] * 2):
                values = fixture(); values[1][key] = value
                with self.assertRaises(AssertionError): self.evaluate(values)

    def test_unknown_failure_missing_duplicate_reordered_or_late_events_fail(self):
        for failure in ('net::ERR_FAILED', 'net::ERR_CONNECTION_RESET', 'canceled', None):
            values = fixture(); values[0][-1]['failure'] = failure
            with self.assertRaises(AssertionError): self.evaluate(values)
        for index in range(4):
            values = fixture(); values[0].pop(index)
            with self.assertRaises(AssertionError): self.evaluate(values)
        values = fixture(); values[0].append(deepcopy(values[0][-1]))
        with self.assertRaises(AssertionError): self.evaluate(values)
        values = fixture(); values[0][1], values[0][2] = values[0][2], values[0][1]
        with self.assertRaises(AssertionError): self.evaluate(values)
        for sequence in (2, 10):
            values = fixture(); values[0][-1]['sequence'] = sequence
            with self.assertRaises(AssertionError): self.evaluate(values)

    def test_no_range_partial_encoded_wrong_content_hash_status_or_console_exception(self):
        for index in range(4):
            for key in ('range', 'if-range'):
                values = fixture(); values[0][index]['request_headers'][key] = 'bytes=0-469'
                with self.assertRaises(AssertionError): self.evaluate(values)
                values = fixture(); values[0][index]['request_headers'].pop(key)
                with self.assertRaises(AssertionError): self.evaluate(values)
        for index in (1, 2):
            for key, value in {'content-type': 'text/html', 'content-length': '469',
                    'content-range': 'bytes 0-469/470', 'accept-ranges': 'bytes',
                    'content-encoding': 'gzip', 'content-disposition': 'attachment; filename=invoice.pdf'}.items():
                values = fixture(); values[0][index]['response_headers'][key] = value
                with self.assertRaises(AssertionError): self.evaluate(values)
            values = fixture(); values[0][index]['status'] = 206
            with self.assertRaises(AssertionError): self.evaluate(values)
        for key, value in {'mimetype': 'text/html', 'source_sha256': 'different',
                           'byte_length': 0}.items():
            values = fixture(); values[0][1][key] = value
            with self.assertRaises(AssertionError): self.evaluate(values)
        values = fixture()
        values[0][1]['byte_length'] = 131073
        for event in values[0][1:3]: event['response_headers']['content-length'] = '131073'
        with self.assertRaises(AssertionError): self.evaluate(values)
        values = fixture(); values[2]['console_errors'] = [{'text': 'Invoice PDF preview failed'}]
        with self.assertRaises(AssertionError): self.evaluate(values)

    def test_callback_keeps_unknowns_native_handler_and_same_request_object(self):
        class PDF:
            def record_request_failed(self, request): return request.native
        class Request:
            method = 'GET'; url = 'http://127.0.0.1:8765/source'; failure = 'net::ERR_ABORTED'; native = False
        class Args: case = 'invoice'
        namespace = dict(pdf=PDF(), args=Args(), report={'failed_requests': []},
            invoice_source_path='/source', ORIGIN='http://127.0.0.1:8765', invoice_failed_requests={})
        exec(compile(ast.Module(body=[NODES['record_failed_request']], type_ignores=[]), '<callback>', 'exec'), namespace)
        request1, request2 = Request(), Request()
        native = Request(); native.native = True
        for request in (request1, request2, native): namespace['record_failed_request'](request)
        self.assertEqual(len(namespace['report']['failed_requests']), 2)
        self.assertIs(namespace['invoice_failed_requests'][request1], namespace['report']['failed_requests'][0])
        self.assertIs(namespace['invoice_failed_requests'][request2], namespace['report']['failed_requests'][1])
        self.assertNotIn(native, namespace['invoice_failed_requests'])

    def test_actual_acceptor_removes_only_same_request_failure_object(self):
        class Page: pass
        class Record: id = 1
        events, observation, kwargs = fixture()
        known, unknown = object(), object()
        same_value_unknown = dict(method='GET', url=kwargs['source_url'], failure='net::ERR_ABORTED')
        known_failure = deepcopy(same_value_unknown)
        report = dict(invoice_source_events=events, invoice_preview_console_errors=[],
            verified_invoice_preview_fetches=[], verified_invoice_preview_cancellations=[],
            failed_requests=[same_value_unknown, known_failure])
        namespace = dict(NS, report=report, invoice_preview_scope={'id': kwargs['scope_id'], 'url': kwargs['page_url']},
            ORIGIN='http://127.0.0.1:8765', invoice_source_path=urlsplit(kwargs['source_url']).path,
            original_hash=kwargs['source_hash'], invoice_phase=kwargs['phase'], invoice_record=Record(),
            invoice_request_ids={known: 1, unknown: 2}, invoice_failed_requests={known: known_failure, unknown: same_value_unknown},
            observe_invoice_preview=lambda width, stage: observation)
        exec(compile(ast.Module(body=[NODES['accept_invoice_preview']], type_ignores=[]), '<acceptor>', 'exec'), namespace)
        namespace['accept_invoice_preview'](1440, 'maintenance-tab')
        self.assertEqual(len(report['failed_requests']), 1)
        self.assertIs(report['failed_requests'][0], same_value_unknown)
        self.assertIs(report['verified_invoice_preview_cancellations'][0]['raw_failure'], known_failure)
        self.assertEqual(len(report['invoice_source_events']), 4)

    def test_original_51_require_conditions_and_guard_bridge_download_are_preserved(self):
        digest = lambda text: hashlib.sha256(text.encode()).hexdigest()
        conditions = Counter(digest(ast.dump(n.args[0])) for n in ast.walk(TREE)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'require')
        expected = Counter(BASELINE['require_condition_hash_counts'])
        self.assertEqual(sum(expected.values()), 51)
        self.assertEqual(BASELINE['source_blob'], '7b1ef09ca54fb545c44fb85bf78bfd68f36637b2')
        self.assertFalse(expected - conditions)
        for name in ('bridge', 'get', 'snapshot'):
            self.assertEqual(digest(ast.dump(NODES[name])), BASELINE['function_ast_sha256'][name], name)
        start = TEXT.index("                        original_response = get(download_href)")
        end = TEXT.index("                        report['cases'].append(f'Browser {width}: rendered history")
        self.assertEqual(digest(TEXT[start:end].replace("                        report['native_download_attempted'] = True\n", "")), BASELINE['native_download_block_sha256'])
        for forbidden in ('route.continue_', 'route.fallback', 'Fetch.enable', 'Network.enable', 'add_init_script'):
            self.assertNotIn(forbidden, TEXT)

    def test_real_scroll_and_settled_geometry_precede_classification(self):
        observer = ast.unparse(NODES['observe_invoice_preview'])
        for phrase in ('scroll_into_view_if_needed()', 'page.mouse.wheel(', 'settled_invoice_preview(entry)',
                       "entry['canvas_regions_reachable'] = True", "'visible-bottom'", "entry['disclosure_closed'] = True"):
            self.assertIn(phrase, observer)
        self.assertNotIn('to_be_in_viewport', observer)
        self.assertLess(observer.index('verify_preview_regions('), observer.index("entry['disclosure_closed']"))
        acceptor = ast.unparse(NODES['accept_invoice_preview'])
        self.assertLess(acceptor.index('observe_invoice_preview'), acceptor.index('verified_preview_fetch('))
        self.assertLess(acceptor.index('verified_preview_fetch('), acceptor.index("report['failed_requests'][:]"))

    def test_full_matrix_has_both_preview_checks_before_native_download(self):
        loop = next(n for n in ast.walk(TREE) if isinstance(n, ast.For) and isinstance(n.target, ast.Tuple)
                    and ast.unparse(n.target) == '(width, height)')
        text = ast.unparse(loop)
        self.assertEqual(ast.literal_eval(loop.iter), ((1440, 900), (390, 780), (320, 640)))
        self.assertIn("accept_invoice_preview(width, 'maintenance-tab')", text)
        self.assertIn("accept_invoice_preview(width, 'maintenance-record')", text)
        self.assertLess(text.index("accept_invoice_preview(width, 'maintenance-record')"), text.index('ExactInvoiceDownload('))

def observation(regions):
    paper = regions[0]['paper']
    return dict(ready=True, error=False, dimensions=[dict(width=paper['width'],height=paper['height'])],
                raster=[regions[0]['raster']])


class ScrollRegions(unittest.TestCase):
    def verify(self, samples, state=None):
        NS['verify_preview_regions'](samples, state or observation(samples))

    def test_realistic_337x477_paper_in_400px_window_is_fully_reachable(self):
        samples = region_fixture(337, 477, 400)
        self.assertLess((samples[0]['region']['bottom']-samples[0]['region']['top'])/477, 1)
        self.verify(samples)
        self.verify(region_fixture(200, 283, 400))

    def test_rejects_unreachable_bottom_width_middle_gap_or_missing_endpoint(self):
        self.assertRaises(AssertionError, self.verify, region_fixture(337, 477, 100))
        samples = region_fixture(337, 477, 400)
        self.assertRaises(AssertionError, self.verify, samples[:1])
        samples[1] = deepcopy(samples[0]); samples[1]['edge'] = 'bottom'
        self.assertRaises(AssertionError, self.verify, samples)
        for index in (0, 1):
            samples = region_fixture(337, 477, 400)
            sample = samples[index]
            sample['clip']['right'] -= 20
            sample['clipping'] = [dict(x=True,y=False,**sample['clip'])]
            sample['region']['right'] = sample['clip']['right']-sample['paper']['left']
            self.assertRaises(AssertionError, self.verify, samples)
        samples = region_fixture(337, 477, 400)
        samples[1]['scroll']['top'] -= 10
        self.assertRaises(AssertionError, self.verify, samples)

    def test_rejects_stale_resized_unstable_zero_hidden_or_forged_geometry(self):
        mutations = [('stable_samples', 6), ('stable_ms', 299), ('unobscured', False)]
        for index in (0, 1):
            for key, value in mutations:
                with self.subTest(index=index,key=key):
                    samples = region_fixture(337,477,400); samples[index][key] = value
                    self.assertRaises(AssertionError, self.verify, samples)
            for key, value in [('raster',dict(width=0,height=477)),
                               ('paper',dict(left=12,top=12,right=131,bottom=181,width=119,height=169))]:
                samples = region_fixture(337,477,400); samples[index][key] = value
                self.assertRaises(AssertionError, self.verify, samples)
        samples = region_fixture(337,477,400)
        state=observation(samples);state['dimensions']=[dict(width=119,height=169)]
        self.assertRaises(AssertionError,self.verify,samples,state)
        for location,key,value in [('clip','bottom',800),('region','bottom',999),
                                    ('scroll','overflow_y','hidden'),('scroll','height',0)]:
            samples=region_fixture(337,477,400);samples[0][location][key]=value
            self.assertRaises(AssertionError,self.verify,samples)

    def test_js_geometry_intersects_viewport_and_nested_clipping_and_detects_overlay(self):
        script = next(ast.literal_eval(n.value) for n in TREE.body if isinstance(n,ast.Assign)
                      and any(isinstance(t,ast.Name) and t.id=='PREVIEW_GEOMETRY' for t in n.targets))
        program = '''const measure=(SCRIPT); let overlay=false;
globalThis.innerWidth=500;globalThis.innerHeight=600;
const box=(left,top,width,height)=>({left,top,right:left+width,bottom:top+height,width,height});
const outer={parentElement:null,clientLeft:0,clientTop:0,clientWidth:450,clientHeight:350,
  getBoundingClientRect:()=>box(0,180,450,350),style:{overflowX:'visible',overflowY:'auto'}};
const scroll={parentElement:outer,clientLeft:0,clientTop:0,clientWidth:361,clientHeight:400,
  scrollTop:0,scrollLeft:0,scrollWidth:361,scrollHeight:501,
  getBoundingClientRect:()=>box(20,150,361,400),style:{overflowX:'auto',overflowY:'auto'}};
const page={contains:e=>e===canvas};
const canvas={parentElement:scroll,width:337,height:477,
  getBoundingClientRect:()=>box(32,162,337,477),closest:()=>page};
const root={querySelector:s=>s.includes('canvas')?canvas:scroll};
globalThis.document={querySelector:()=>root,elementFromPoint:()=>overlay?{}:canvas,
  compatMode:'CSS1Compat',documentElement:{clientWidth:500,clientHeight:600}};
globalThis.getComputedStyle=e=>e.style;
const a=measure();overlay=true;const b=measure();process.stdout.write(JSON.stringify([a,b]));'''.replace('SCRIPT',script)
        a,b=json.loads(subprocess.run(['node','-e',program],check=True,capture_output=True,text=True).stdout)
        self.assertEqual(a['clip'],dict(left=20,top=180,right=381,bottom=530))
        self.assertEqual(a['region'],dict(left=0,top=18,right=337,bottom=368))
        self.assertTrue(a['unobscured']);self.assertFalse(b['unobscured'])
        self.assertEqual(len(a['clipping']),2)

    def test_settling_refreshes_initial_raster_and_waits_past_resize_debounce(self):
        class Page:
            sample=0
            waits=[]
            def evaluate(self,script):
                old=self.sample<3
                if script=='state':
                    return dict(ready=True,error=False,dimensions=[dict(width=119 if old else 337,height=169 if old else 477)],
                        raster=[dict(width=119 if old else 337,height=169 if old else 477)])
                self.sample+=1
                return region_fixture(119,169,400)[0] if old else region_fixture(337,477,400)[0]
            def wait_for_timeout(self,ms):self.waits.append(ms)
        page=Page();namespace=dict(page=page,PREVIEW_STATE='state',PREVIEW_GEOMETRY='geometry')
        exec(compile(ast.Module(body=[NODES['settled_invoice_preview']],type_ignores=[]),'<settler>','exec'),namespace)
        entry={};result=namespace['settled_invoice_preview'](entry)
        self.assertEqual(entry['raster'],[dict(width=337,height=477)])
        self.assertEqual(result['stable_samples'],7)
        self.assertGreaterEqual(sum(page.waits),450)
        self.assertEqual(result['stable_ms'],300)

    def test_first_ready_resize_gap_is_settled_before_observer_branches(self):
        # Regression for b91e4bd CI: first wait resolved, then fit removed the
        # canvas before the observer's one-shot sample. No error or timeout.
        class Page:
            sample=0
            waits=[]
            def evaluate(self,script):
                gap=self.sample in (1,2,3)
                if script=='state':
                    return dict(ready=not gap,error=False,
                        raster=[] if gap else [dict(width=337,height=477)])
                self.sample+=1
                return None if gap else region_fixture(337,477,400)[0]
            def wait_for_timeout(self,ms):self.waits.append(ms)
        page=Page();namespace=dict(page=page,PREVIEW_STATE='state',PREVIEW_GEOMETRY='geometry')
        exec(compile(ast.Module(body=[NODES['settled_invoice_preview']],type_ignores=[]),'<settler>','exec'),namespace)
        entry={};result=namespace['settled_invoice_preview'](entry)
        self.assertTrue(entry['ready'])
        self.assertEqual(result['stable_samples'],7)
        self.assertGreaterEqual(sum(page.waits),500)
        observer=NODES['observe_invoice_preview']
        wait_try=next(n for n in ast.walk(observer) if isinstance(n,ast.Try))
        self.assertIn('settled_invoice_preview(entry)',ast.unparse(wait_try.body[-1]))
        self.assertNotIn('entry.update',ast.unparse(ast.Module(body=wait_try.finalbody,type_ignores=[])))
        self.assertIn("entry['wait_error']",ast.unparse(wait_try.handlers[0]))

    def test_flags_separate_selection_attempt_and_completed_acceptance(self):
        self.assertIn('full_invoice_browser_selected=True',TEXT)
        self.assertIn('full_invoice_browser_executed=False, native_download_attempted=False',TEXT)
        # Completion markers are set only after all preview, native, error and
        # protected-state checks pass, not when the full mode is selected.
        marker='report.update(full_invoice_browser_executed=True, native_download_reexecuted=True)'
        self.assertEqual(TEXT.count(marker),1)
        self.assertGreater(TEXT.index(marker),TEXT.index("report.update(status='PASS'"))
        self.assertEqual(TEXT.count("report['native_download_attempted'] = True"),1)

def measure(options=None):
    script = next(ast.literal_eval(n.value) for n in TREE.body if isinstance(n, ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='PREVIEW_GEOMETRY' for t in n.targets))
    program = '''const measure=(SCRIPT), records=RECORDS, options=OPTIONS;
const result=records.map(record=>{
  globalThis.innerWidth=record.viewport.width;globalThis.innerHeight=record.viewport.height;
  const nodes=record.clipping.map((c,i)=>({parentElement:null,clientLeft:0,clientTop:0,
    tagName:i===5?'HTML':i===4?'BODY':'DIV',clientWidth:c.right-c.left,clientHeight:c.bottom-c.top,
    getBoundingClientRect:()=>({left:c.left,top:c.top,right:c.right,bottom:c.bottom,
      width:c.right-c.left,height:c.bottom-c.top}),style:{overflowX:c.x?'auto':'visible',overflowY:c.y?'auto':'visible'}}));
  for(let i=0;i<nodes.length-1;i++)nodes[i].parentElement=nodes[i+1];
  if(options.bodyClip){nodes[4].getBoundingClientRect=()=>({left:0,top:100,right:390,bottom:300,width:390,height:200});nodes[4].clientHeight=200;}
  const scroll=nodes[0];Object.assign(scroll,{scrollTop:record.scroll.top,scrollLeft:0,
    scrollWidth:record.scroll.extent_width,scrollHeight:record.scroll.extent_height});
  const page={contains:e=>e===canvas};
  const canvas={parentElement:scroll,width:record.raster.width,height:record.raster.height,
    getBoundingClientRect:()=>record.paper,closest:()=>page};
  const root={querySelector:s=>s.includes('canvas')?canvas:scroll};
  const otherRoot={tagName:'HTML',clientWidth:390,clientHeight:780};
  globalThis.document={querySelector:()=>root,elementFromPoint:()=>canvas,
    compatMode:options.quirks?'BackCompat':'CSS1Compat',body:nodes[4],
    documentElement:options.lookalike?otherRoot:nodes[5],
    scrollingElement:options.bodyScroller?nodes[4]:options.notScroller?otherRoot:nodes[5]};
  globalThis.getComputedStyle=e=>e.style;
  return {...measure(),edge:record.edge,stable_samples:7,stable_ms:300};
});process.stdout.write(JSON.stringify(result));'''
    program=program.replace('SCRIPT',script).replace('RECORDS',json.dumps(RECORDED)).replace('OPTIONS',json.dumps(options or {}))
    return json.loads(subprocess.run(['node','-e',program],check=True,capture_output=True,text=True).stdout)


class RootViewport(unittest.TestCase):
    def verify(self, samples):
        return NS['verify_preview_regions'](samples,dict(ready=True,error=False,
            dimensions=[dict(width=310,height=439)],raster=[dict(width=310,height=439)]))

    def test_recorded_scroll_offset_uses_actual_standards_root_viewport(self):
        samples=measure()
        self.verify(samples)
        self.assertEqual(samples[0]['clip'],dict(left=26,top=262.703125,right=364,bottom=642.703125))
        self.assertEqual(samples[0]['region'],dict(left=0,top=0,right=310,bottom=368))
        self.assertEqual(samples[1]['region'],dict(left=0,top=71,right=310,bottom=439))
        for sample,old in zip(samples,RECORDED):
            root=sample['clipping'][-1]
            self.assertEqual(root['raw_client_box'],{k:old['clipping'][-1][k] for k in ('left','top','right','bottom')})
            self.assertEqual(root['raw_client_box']['bottom'],-883)
            self.assertEqual(root['box_kind'],'document_viewport')
            self.assertTrue(root['is_document_element']);self.assertTrue(root['is_scrolling_element'])
            self.assertFalse(root['is_body']);self.assertEqual(root['tag_name'],'HTML')
            self.assertEqual({k:root[k] for k in ('left','top','right','bottom')},dict(left=0,top=0,right=390,bottom=780))
            for current,prior in zip(sample['clipping'][:-1],old['clipping'][:-1]):
                self.assertEqual({k:current[k] for k in ('left','top','right','bottom')},
                                 {k:prior[k] for k in ('left','top','right','bottom')})

    def test_html_tag_alone_wrong_root_wrong_scroller_and_quirks_do_not_exempt(self):
        for option in ('lookalike','notScroller','bodyScroller','quirks'):
            with self.subTest(option=option):
                samples=measure({option:True})
                self.assertEqual(samples[0]['clipping'][-1]['box_kind'],'client_box')
                self.assertEqual(samples[0]['clip']['bottom'],-883)
                self.assertRaises(AssertionError,self.verify,samples)

    def test_body_and_ordinary_ancestor_clipping_are_not_skipped(self):
        samples=measure({'bodyClip':True})
        self.assertEqual(samples[0]['clipping'][-2]['box_kind'],'client_box')
        self.assertTrue(samples[0]['clipping'][-2]['is_body'])
        self.assertEqual(samples[0]['clip']['bottom'],300)
        self.assertRaises(AssertionError,self.verify,samples)

    def test_report_verifier_rejects_identity_or_box_substitution(self):
        for key,value in [('is_document_element',False),('is_scrolling_element',False),
                          ('is_body',True),('tag_name','BODY'),('box_kind','client_box')]:
            samples=measure();samples[0]['clipping'][-1][key]=value
            self.assertRaises(AssertionError,self.verify,samples)
        samples=measure();samples[0]['clipping'][-2]['box_kind']='document_viewport'
        self.assertRaises(AssertionError,self.verify,samples)
        samples=measure();samples[0]['clipping'][-2]['bottom']=7800
        self.assertRaises(AssertionError,self.verify,samples)

    def test_source_scope_native_and_scroll_behavior_functions_are_identical(self):
        for name,digest in UNCHANGED_FUNCTION_HASHES.items():
            self.assertEqual(hashlib.sha256(ast.dump(NODES[name]).encode()).hexdigest(),digest,name)

RECORDED = [{'paper': {'left': 40, 'top': 274.703125, 'right': 350, 'bottom': 713.703125, 'width': 310, 'height': 439}, 'clip': {'left': 26, 'top': 262.703125, 'right': 364, 'bottom': -883}, 'region': {'left': 0, 'top': 0, 'right': 310, 'bottom': -1157.703125}, 'clipping': [{'x': True, 'y': True, 'left': 26, 'top': 262.703125, 'right': 364, 'bottom': 642.703125}, {'x': True, 'y': True, 'left': 26, 'top': 153.703125, 'right': 364, 'bottom': 671.703125}, {'x': True, 'y': True, 'left': 13, 'top': -394.484375, 'right': 377, 'bottom': 766.515625}, {'x': True, 'y': True, 'left': 0, 'top': -1663, 'right': 390, 'bottom': 780}, {'x': True, 'y': True, 'left': 0, 'top': -1663, 'right': 390, 'bottom': 780}, {'x': True, 'y': True, 'left': 0, 'top': -1663, 'right': 390, 'bottom': -883}], 'viewport': {'width': 390, 'height': 780}, 'unobscured': False, 'raster': {'width': 310, 'height': 439}, 'scroll': {'top': 0, 'left': 0, 'width': 338, 'height': 380, 'extent_width': 338, 'extent_height': 463, 'overflow_y': 'auto'}, 'stable_samples': 7, 'stable_ms': 300, 'edge': 'top'}, {'paper': {'left': 40, 'top': 191.703125, 'right': 350, 'bottom': 630.703125, 'width': 310, 'height': 439}, 'clip': {'left': 26, 'top': 262.703125, 'right': 364, 'bottom': -883}, 'region': {'left': 0, 'top': 71, 'right': 310, 'bottom': -1074.703125}, 'clipping': [{'x': True, 'y': True, 'left': 26, 'top': 262.703125, 'right': 364, 'bottom': 642.703125}, {'x': True, 'y': True, 'left': 26, 'top': 153.703125, 'right': 364, 'bottom': 671.703125}, {'x': True, 'y': True, 'left': 13, 'top': -394.484375, 'right': 377, 'bottom': 766.515625}, {'x': True, 'y': True, 'left': 0, 'top': -1663, 'right': 390, 'bottom': 780}, {'x': True, 'y': True, 'left': 0, 'top': -1663, 'right': 390, 'bottom': 780}, {'x': True, 'y': True, 'left': 0, 'top': -1663, 'right': 390, 'bottom': -883}], 'viewport': {'width': 390, 'height': 780}, 'unobscured': False, 'raster': {'width': 310, 'height': 439}, 'scroll': {'top': 83, 'left': 0, 'width': 338, 'height': 380, 'extent_width': 338, 'extent_height': 463, 'overflow_y': 'auto'}, 'stable_samples': 7, 'stable_ms': 300, 'edge': 'bottom'}]

UNCHANGED_FUNCTION_HASHES = {'verified_preview_fetch': '361ef8cfefa4b8df8feea7aa5c008e8779e8f82db5231508dff3232051aa17f0', 'observe_invoice_source': 'ec5cfd5d1104c2dc8d657ec5eb1bdc4a53e201c6d09edc1beae07d8475e49b2e', 'record_failed_request': '7e738421df561c99cac0c9eeaf3636ff1c103de1a1cb55e5c9cd820dc1e3292d', 'accept_invoice_preview': '232002f99f57d640a38521b59717edcfd45f2ba5cd89bed6f5083d9e58e88b7a', 'settled_invoice_preview': '0d1ccf4bff73259cad4c9e7990a4f13b7c7815386fa0d7a295eb8f306b764e41', 'observe_invoice_preview': 'd5e5e2d3ec20609273c3bdce56e0de0961fd7a2141d7e098c5211920be58012f', 'bridge': 'd79e7c27baf7b9cde62f72e1b04c5996f8d6289fee8530f148169fbea3752916', 'get': '3bd4e1449ad02e2ae13d05a4282060675db7e9c2edc8301171aa385963407c3d', 'snapshot': '960dd3cdf7a16c7f9e64e34e6dac50d2d07076af37d8b4f5ee6519f1d65e71d0'}


if __name__ == '__main__':
    unittest.main()
