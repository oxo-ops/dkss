#!/usr/bin/env python3
"""Run only full PR377 invoice acceptance with explicit preview and native download evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

APP_SHA = '30d4dfeee97f69bd00650c6bf56a5ce234f34437'
APP_TREE = '31bb88b2d7a1a93f4c52f5aeefd59e97a8c8d3ea'
FIXED_HELPER_BLOB = '44e1612f2ca59eca80a2c6a436426bc722af18a7'
FIXED_ACCEPTANCE_BLOB = '81840fd3ea281fd198ce1101794c1c887eb7d9c3'
RECEIVER_BLOB = 'e84e269a1f72e9772bd33284024601f31644d1c0'
CONTAINER_IMAGE = 'mcr.microsoft.com/playwright/python@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d'
PDF_NAVIGATION_BLOB = '4573aa6f07666f1d4e508b7352cc4cd42df0a323'
PRIOR_INDEX_SHA256 = '3d135f66de36f03aeeb38abd05890f6d0eb343cd5979123ee3502e445f7cc4d9'
VALIDATION_FILES = {
    '.github/workflows/pr377-supplemental-browser.yml', 'README.md',
    'harness/confirmation_acceptance.py', 'harness/validate_remaining.py',
    'harness/acceptance.py', 'harness/prior-evidence.json',
    'harness/native_pdf_navigation.py', 'harness/exact_invoice_download.py',
}
FROZEN_FILES = {
    'tests/common_priority_browser/acceptance.py': '4375da234da7d2dc8b1939db8f8772cd08d6ef1e',
    'tests/common_priority_browser/stage2_acceptance.py': 'e3a4e4695df68c2f38b5e2fef5b483ac70da9951',
    'tests/common_priority_browser/run-isolated.sh': 'f1be008f4e441e09b8f22ff41772d114fb0ba38d',
    'tests/common_priority_browser/run-stage2-isolated.sh': 'e35a5817ed89233f6fe132de5b71d757f066933a',
    'tests/video_connected_browser/acceptance.py': '97f6b6707d88c278cadd975b858762d112f37d56',
    'tests/video_connected_browser/run-isolated.sh': 'f1be008f4e441e09b8f22ff41772d114fb0ba38d',
    'tests/video_connected_browser/confirmation_acceptance.py': '77038626212de6c5b1c569ad420274e97a16cfc8',
    'tests/history_presentation_browser/guard/sitecustomize.py': 'fecc07a6a8d0ddbbe19cc2cbd4d234dc209e7cef',
}
COPIES = (
    'tests/video_connected_browser/run-isolated.sh',
    'tests/history_presentation_browser/guard/sitecustomize.py',
)
CURRENT_CASES = ('invoice',)


def require(value, message):
    if not value:
        raise AssertionError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def git(repo, *arguments):
    return subprocess.check_output(['git', '-C', str(repo), *arguments], text=True).strip()


def identity(path):
    raw = path.read_bytes()
    return dict(git_blob=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
                sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))


def verify_sources(args):
    app, validation = args.application, args.validation
    require(git(app, 'rev-parse', 'HEAD') == APP_SHA, 'Application commit changed')
    require(git(app, 'rev-parse', 'HEAD^{tree}') == APP_TREE, 'Application tree changed')
    require(not git(app, 'status', '--porcelain', '--untracked-files=all'), 'Application is not clean')
    require(git(validation, 'rev-parse', 'HEAD') == args.validation_sha, 'Validation commit mismatch')
    require(not git(validation, 'status', '--porcelain', '--untracked-files=all'), 'Validation checkout is not clean')
    require(set(git(validation, 'ls-tree', '-r', '--name-only', 'HEAD').splitlines()) == VALIDATION_FILES,
            'Validation branch has unexpected files')
    files = {}
    for relative, expected in FROZEN_FILES.items():
        path = app / relative
        require(not path.is_symlink(), 'Frozen harness may not be a symlink: ' + relative)
        value = identity(path)
        require(value['git_blob'] == expected == git(app, 'rev-parse', 'HEAD:' + relative),
                'Frozen harness changed: ' + relative)
        files[relative] = value
    validation_files = {}
    for relative in sorted(VALIDATION_FILES):
        value = identity(validation / relative)
        require(value['git_blob'] == git(validation, 'rev-parse', 'HEAD:' + relative),
                'Validation file differs from commit: ' + relative)
        validation_files[relative] = value
    require(validation_files['harness/confirmation_acceptance.py']['git_blob'] == FIXED_HELPER_BLOB,
            'Confirmation helper differs from the reviewed external correction')
    require(validation_files['harness/acceptance.py']['git_blob'] == FIXED_ACCEPTANCE_BLOB,
            'Acceptance entry point differs from the reviewed full invoice preview acceptance')
    require(validation_files['harness/native_pdf_navigation.py']['git_blob'] == PDF_NAVIGATION_BLOB,
            'PDF navigation classifier differs from the reviewed helper')
    require(validation_files['harness/exact_invoice_download.py']['git_blob'] == RECEIVER_BLOB,
            'Response-only receiver differs from the reviewed helper')
    prior_evidence(args)
    return dict(application_commit=APP_SHA, application_tree=APP_TREE,
                validation_commit=args.validation_sha,
                validation_tree=git(validation, 'rev-parse', 'HEAD^{tree}'),
                frozen_files=files, validation_files=validation_files)


def harness_root(args):
    return args.artifacts.parent / 'pr377-invoice-document-scroll-harness'


def verify_copies(args):
    target = harness_root(args)
    for relative in COPIES:
        require((target / relative).read_bytes() == (args.application / relative).read_bytes(),
                'Copied original harness/guard changed: ' + relative)
    for name in ('acceptance.py', 'confirmation_acceptance.py', 'native_pdf_navigation.py', 'exact_invoice_download.py'):
        require((target / 'tests/video_connected_browser' / name).read_bytes()
                == (args.validation / 'harness' / name).read_bytes(),
                'Separate reviewed helper changed: ' + name)
    # The acceptance entry point still prepends app/ and app/tests/ to sys.path.
    # Neither may shadow validation-side helpers in the script directory.
    for directory in (args.application, args.application / 'tests',
                      target / 'tests/history_presentation_browser/guard'):
        for name in ('confirmation_acceptance', 'native_pdf_navigation', 'exact_invoice_download'):
            require(not (directory / (name + '.py')).exists()
                    and not (directory / name).exists(), 'Ambiguous helper import: ' + name)


def prepare(args):
    manifest = verify_sources(args)
    target = harness_root(args)
    require(not target.exists(), 'External harness must be a new directory')
    require(not target.is_relative_to(args.application)
            and not target.is_relative_to(args.validation), 'Harness must be outside both checkouts')
    for relative in COPIES:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.application / relative, destination)
    for name in ('acceptance.py', 'confirmation_acceptance.py', 'native_pdf_navigation.py', 'exact_invoice_download.py'):
        destination = target / 'tests/video_connected_browser' / name
        shutil.copyfile(args.validation / 'harness' / name, destination)
    verify_copies(args)
    manifest.update(
        verification_kind='supplemental_separate_fixture_harness_not_original_pr_ci',
        copied_original_files=list(COPIES),
        modified_external_helpers=[dict(application_path='tests/video_connected_browser/' + name,
                                        validation_path='harness/' + name,
                                        executed_path=str(target / 'tests/video_connected_browser' / name))
                                   for name in ('acceptance.py',)],
        retained_unexecuted_confirmation_helper='harness/confirmation_acceptance.py',
        added_external_helpers=[dict(validation_path='harness/' + name,
                                     executed_path=str(target / 'tests/video_connected_browser' / name))
                                for name in ('native_pdf_navigation.py', 'exact_invoice_download.py')],
        prior_evidence_index_sha256=PRIOR_INDEX_SHA256,
        current_run_browser_cases=list(CURRENT_CASES),
        current_run_http_cases=[],
        current_invoice_preview_requirements='six rendered exact-source previews with continuous scroll reachability',
        application_checkout_modified=False,
        prepared_utc=now())
    write_json(args.artifacts / 'harness-provenance.json', manifest)


def prior_evidence(args):
    path = args.validation / 'harness/prior-evidence.json'
    require(identity(path)['sha256'] == PRIOR_INDEX_SHA256, 'Prior evidence index changed')
    prior = json.loads(path.read_text())
    require(prior['application_commit'] == APP_SHA and prior['application_tree'] == APP_TREE,
            'Prior evidence application mismatch')
    require(prior['run_id'] == 43075650114 and prior['artifact_id'] == 13882316519,
            'Wrong previous invoice evidence run')
    require(prior['http_passed'] == 0 and prior['browser_passed'] == 0 and prior['source_unchanged'] is True
            and prior['overall_status'] == 'FAILED_OR_INCOMPLETE', 'Latest invoice failure must remain intact')
    require(len(prior['scenarios']) == 1 and prior['scenarios'][0]['id'] == 'browser-connected-invoice'
            and prior['scenarios'][0]['passed'] is False, 'Current scope remains the failed invoice browser case')
    reached = prior['actual_reached_evidence']
    require(reached['native_download_count'] == reached['native_transfer_count'] == 1
            and reached['reachable_preview_count'] == reached['verified_preview_proof_count']
            == reached['classified_preview_cancellation_count'] == 2
            and reached['completed_component_widths'] == [1440]
            and reached['final_protected_records_unchanged_field_present'] is False,
            'Partial components must not be relabeled as full acceptance')
    previous = prior['previous_evidence_reference']
    require(previous['run_id'] == 43072294744 and previous['http_passed'] == 0 and previous['browser_passed'] == 0
            and previous['overall_status'] == 'FAILED_OR_INCOMPLETE', 'Earlier invoice failure must remain separate')
    return prior


def scenarios():
    return [dict(id='browser-connected-' + case, folder='connected-' + case,
                 family='external', case=case, browser=True) for case in CURRENT_CASES]


def command(args, scenario):
    require(any(all(scenario.get(key) == value for key, value in expected.items())
                for expected in scenarios()), 'No other scenario may execute in this run')
    script = harness_root(args) / 'tests/video_connected_browser/run-isolated.sh'
    return ['bash', str(script), str(args.application), str(args.python), '--expected-sha', APP_SHA,
            '--case', scenario['case'], '--run-browser', '--chromium', str(args.chromium),
            '--native-invoice-download-http']


def experiment_context(args):
    """Record the requested CI location/selection, not an authorization mechanism."""
    require(os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('GITHUB_REPOSITORY') == 'oxo-ops/dkss'
            and os.environ.get('GITHUB_SHA') == args.validation_sha,
            'This synthetic download experiment is only selected in the official CI workflow')
    run_id, attempt = os.environ.get('GITHUB_RUN_ID', ''), os.environ.get('GITHUB_RUN_ATTEMPT', '')
    require(run_id.isdigit() and attempt.isdigit(), 'CI run identity required')
    runtime = json.loads((args.artifacts / 'runtime-manifest.json').read_text())
    require(runtime['application_commit'] == APP_SHA and runtime['application_tree'] == APP_TREE
            and runtime['validation_commit'] == args.validation_sha
            and runtime['validation_tree'] == git(args.validation, 'rev-parse', 'HEAD^{tree}'),
            'Existing runtime/source identity differs')
    require(runtime['container'] == CONTAINER_IMAGE and runtime['playwright'] == '1.62.0'
            and runtime['node'] == 'v24.22.2' and runtime['verified_requirement_count'] == 38
            and runtime['python'].startswith('3.12.'), 'Existing pinned runtime verification required')
    return dict(location_record_only_not_authorization=True, github_run_id=run_id,
                github_run_attempt=attempt, application_commit=APP_SHA, application_tree=APP_TREE,
                validation_commit=args.validation_sha, validation_tree=runtime['validation_tree'],
                container=runtime['container'], python=runtime['python'], node=runtime['node'],
                playwright=runtime['playwright'], verified_requirement_count=38,
                browser_case='invoice', cli_flag='--native-invoice-download-http',
                receiver_scope='one immutable synthetic original GET on 127.0.0.1:8765 per download',
                wrapper_and_audit_guard_unchanged=True, native_pdf_helper_unchanged=True)


def run(args):
    require(args.python and args.python.is_file() and os.access(args.python, os.X_OK), 'Executable Python required')
    require(args.chromium and args.chromium.is_file() and os.access(args.chromium, os.X_OK), 'Executable Chromium required')
    verify_sources(args)
    verify_copies(args)
    context = experiment_context(args)
    context_path = args.artifacts / 'invoice-experiment-context.json'
    require(not context_path.exists(), 'Refusing to reuse experiment context evidence')
    write_json(context_path, context)
    ledger = dict(application_commit=APP_SHA, validation_commit=args.validation_sha,
                  started_utc=now(), scenarios=[dict(s, execution='NOT_RUN', exit_code=None) for s in scenarios()])
    ledger_path = args.artifacts / 'scenario-exits.json'
    require(not ledger_path.exists(), 'Refusing to reuse scenario execution evidence')
    write_json(ledger_path, ledger)
    for scenario in ledger['scenarios']:
        verify_sources(args)
        verify_copies(args)
        output = args.artifacts / scenario['folder']
        output.mkdir(parents=True, exist_ok=True)
        require(not (output / 'browser-result.json').exists(), 'Refusing to reuse scenario report')
        scenario.update(execution='STARTED', started_utc=now())
        write_json(ledger_path, ledger)
        environment = os.environ.copy()
        environment['DKSS_BROWSER_ARTIFACT_DIR'] = str(output)
        # The byte-identical original env -i wrapper strips this inherited
        # environment before any application code or fixture is imported.
        with (output / 'execution.log').open('w') as log:
            try:
                completed = subprocess.run(command(args, scenario), cwd=args.application, env=environment,
                                           stdout=log, stderr=subprocess.STDOUT, check=False)
                scenario.update(execution='FINISHED', exit_code=completed.returncode)
            except OSError as error:
                scenario.update(execution='LAUNCH_FAILED', error_type=type(error).__name__)
        scenario['finished_utc'] = now()
        write_json(ledger_path, ledger)
        print(scenario['id'], scenario['execution'], scenario['exit_code'], flush=True)
        # Integrity failures stop further execution. Ordinary test failures do
        # not skip any independent case, and remain failures in the aggregate.
        verify_sources(args)
        verify_copies(args)
    ledger['finished_utc'] = now()
    write_json(ledger_path, ledger)
    return 0 if all(s['execution'] == 'FINISHED' and s['exit_code'] == 0 for s in ledger['scenarios']) else 1


def validate_report(report, scenario):
    require(report['candidate_sha'] == APP_SHA and report['candidate_tree'] == APP_TREE, 'Report source mismatch')
    require(report['fixture_only'] is True and report['production_accessed'] is False, 'Report isolation mismatch')
    if scenario['case']:
        require(report['scenario'] == scenario['case'], 'Report scenario mismatch')
    if scenario['browser']:
        require(report['status'] == 'PASS' and report['browser_acceptance_passed'] is True
                and report['browser_started'] is True, 'Browser did not pass')
    else:
        require(report['status'] == 'PREFLIGHT_PASS_BROWSER_NOT_RUN' and report['browser_started'] is False
                and report['browser_acceptance_passed'] is False, 'HTTP-only report mismatch')
    require(report['full_invoice_browser_selected'] is True and report['native_download_attempted'] is True,
            'Full invoice/native paths were not selected and reached')
    require(report['diagnostic_only'] is False and report['full_invoice_browser_executed'] is True
            and report['native_download_reexecuted'] is True, 'Diagnostic report cannot pass full invoice acceptance')
    require(report['native_invoice_http_experiment'] is True
            and report['protected_records_unchanged'] is True, 'Native experiment/protected-record evidence missing')
    transfers, downloads = report['invoice_http_transfers'], report['invoice_downloads']
    require([x['width'] for x in transfers] == [1440, 390, 320]
            and [x['width'] for x in downloads] == [1440, 390, 320], 'All three native downloads required')
    for transfer, download in zip(transfers, downloads):
        require(transfer['bound_address'] == ['127.0.0.1', 8765] and transfer['status'] == 200
                and transfer['content_type'] == 'application/pdf'
                and transfer['cleanup_complete'] is True and transfer['expired'] is False
                and not transfer['errors'] and not transfer['rejected']
                and len(transfer['accepted']) == 1, 'Receiver transfer/cleanup did not pass')
        accepted = transfer['accepted'][0]
        require(accepted['write_complete'] is True and accepted['method'] == 'GET'
                and accepted['host'] == '127.0.0.1:8765' and accepted['peer'] == '127.0.0.1'
                and accepted['path'] == download['href']
                and accepted['source_sha256'] == transfer['source_sha256']
                and accepted['byte_length'] == transfer['byte_length'], 'Confined one-shot transfer mismatch')
        require(download['failure'] is None
                and download['url'] == transfer['source_url'] == 'http://127.0.0.1:8765' + download['href']
                and download['suggested_filename'] == download['download_attribute']
                and download['saved_file_sha256'] == transfer['source_sha256'] == transfers[0]['source_sha256']
                and download['saved_file_byte_length'] == transfer['byte_length'],
                'Actual native saved-file identity missing or mismatched')
    validate_previews(report)
    for name in ('page_errors', 'blocked_requests', 'failed_gets', 'failed_requests'):
        require(not report[name], 'Unexpected browser failure remains: ' + name)


def verify_preview_regions(regions, observation):
    """Two real scroll positions must cover the entire stable rendered page.

    One CSS pixel is only for fractional border/scroll rounding. There is no
    percentage visibility exemption: both full width and continuous full height
    must be reached within the actual ancestor-clipped browser viewport.
    """
    require(len(regions) == 2 and [r['edge'] for r in regions] == ['top', 'bottom'],
            'Both real preview scroll endpoints are required')
    first, last = regions
    size = (first['paper']['width'], first['paper']['height'])
    require(size[0] > 2 and size[1] > 2 and observation.get('ready') is True and
            observation.get('error') is False and
            observation.get('dimensions') == [dict(width=size[0], height=size[1])] and
            observation.get('raster') == [first['raster']], 'Final preview dimensions or raster are stale')
    for sample in regions:
        paper, clip, region, scroll = (sample[key] for key in ('paper', 'clip', 'region', 'scroll'))
        viewport = sample['viewport']
        actual_clip = dict(left=0,top=0,right=viewport['width'],bottom=viewport['height'])
        for ancestor in sample['clipping']:
            bounds = {key: ancestor[key] for key in ('left','top','right','bottom')}
            root = (sample.get('document_compat_mode') == 'CSS1Compat' and
                    ancestor.get('is_document_element') is True and ancestor.get('is_scrolling_element') is True)
            if root:
                require(ancestor.get('box_kind') == 'document_viewport' and ancestor.get('tag_name') == 'HTML' and
                        ancestor.get('is_body') is False and bounds == dict(left=0,top=0,
                            right=sample['document_viewport']['width'],bottom=sample['document_viewport']['height']),
                        'Actual standards-mode scrolling root must use viewport coordinates')
            else:
                require(ancestor.get('box_kind') == 'client_box' and bounds == ancestor.get('raw_client_box'),
                        'Ordinary ancestor clipping cannot be omitted or replaced with viewport bounds')
            for axis, start, end in (('x','left','right'), ('y','top','bottom')):
                if ancestor[axis]:
                    actual_clip[start] = max(actual_clip[start], ancestor[start])
                    actual_clip[end] = min(actual_clip[end], ancestor[end])
        require(clip == actual_clip and viewport['width'] > 0 and viewport['height'] > 0 and
                abs(paper['right']-paper['left']-paper['width']) < 0.01 and
                abs(paper['bottom']-paper['top']-paper['height']) < 0.01,
                'Preview clipping does not match the real viewport and ancestors')
        require(sample.get('stable_samples', 0) >= 7 and sample.get('stable_ms', 0) >= 300 and
                (paper['width'], paper['height']) == size and sample['raster'] == first['raster'] and
                sample['raster']['width'] > 0 and sample['raster']['height'] > 0,
                'Preview resized or raster changed between endpoint captures')
        require(sample.get('unobscured') is True and clip['right'] > clip['left'] and
                clip['bottom'] > clip['top'] and scroll['width'] > 0 and scroll['height'] > 0 and
                scroll['overflow_y'] in ('auto', 'scroll'), 'Preview scroll window is clipped or obscured')
        expected = dict(left=max(paper['left'], clip['left'])-paper['left'],
            top=max(paper['top'], clip['top'])-paper['top'],
            right=min(paper['right'], clip['right'])-paper['left'],
            bottom=min(paper['bottom'], clip['bottom'])-paper['top'])
        require(region == expected and region['right']-region['left'] > 2 and
                region['bottom']-region['top'] > 2 and region['left'] <= 1 and
                region['right'] >= size[0]-1, 'Actual visible region does not cover the full page width')
        require(scroll['left'] <= 1 and scroll['extent_width'] >= scroll['width'] and
                scroll['extent_height'] >= scroll['height'], 'Invalid preview scroll geometry')
    require(first['scroll']['top'] <= 1 and
            abs(last['scroll']['top']-(last['scroll']['extent_height']-last['scroll']['height'])) <= 1 and
            first['region']['top'] <= 1 and last['region']['bottom'] >= size[1]-1 and
            first['region']['bottom'] + 1 >= last['region']['top'],
            'Preview top/bottom scrolling leaves an unreachable page region')

def validate_previews(report):
    expected = [(width, stage) for width in (1440, 390, 320)
                for stage in ('maintenance-tab', 'maintenance-record')]
    observations, proofs = report['invoice_preview_observations'], report['verified_invoice_preview_fetches']
    require([(x['width'], x['stage']) for x in observations] == expected
            and [(x['width'], x['stage']) for x in proofs] == expected, 'All six ordered previews/proofs required')
    require(len({p['request_id'] for p in proofs}) == 6 and len({p['scope_id'] for p in proofs}) == 6,
            'Preview requests and scopes must be distinct')
    require(not report['invoice_preview_console_errors'], 'Invoice preview console error remains')
    events = report['invoice_source_events']
    require([e['sequence'] for e in events] == list(range(1, len(events) + 1)), 'Source event sequence differs')
    expected_cancellations = []
    for observation, proof in zip(observations, proofs):
        width, stage = observation['width'], observation['stage']
        phase = f'width:{width}/{stage}'
        source = next(t for t in report['invoice_http_transfers'] if t['width'] == width)
        require(proof['phase'] == proof['scope_id'] == observation['phase'] == observation['scope_id'] == phase
                and proof['page_url'] == observation['url']
                and proof['source_url'] == source['source_url']
                and proof['source_sha256'] == source['source_sha256']
                and proof['byte_length'] == source['byte_length']
                and proof['classification'] == 'verified_rendered_preview_fetch'
                and proof['abort_caller_proven'] is False, 'Preview proof identity differs')
        require(observation['present'] is True and observation['ready'] is True
                and observation['error'] is False and not observation.get('wait_error')
                and observation['total'] == observation['current'] == '1'
                and 'スクロールでページ移動' in observation['status']
                and observation['source_base'] == urlsplit(source['source_url']).path
                and observation['record_key'] == observations[0]['record_key'] and observation['record_key']
                and observation['disclosure_open'] is True and observation['disclosure_closed'] is True
                and observation['canvas_regions_reachable'] is True, 'Preview is not fully rendered and visibly verified')
        verify_preview_regions(observation['preview_regions'], observation)
        for name in ('dimensions', 'raster'):
            values = observation[name]
            require(len(values) == 1 and values[0]['width'] > 0 and values[0]['height'] > 0,
                    'Positive one-page raster/dimensions required')
        scoped = [event for event in events if event.get('preview_scope_id') == phase]
        require(len(scoped) == 4 and [e['event'] for e in scoped[:3]] == ['request', 'bridge_response', 'response']
                and scoped[-1]['event'] in ('requestfinished', 'requestfailed')
                and [e['sequence'] for e in scoped] == proof['event_sequences']
                and scoped[-1]['sequence'] <= observation['source_event_end'] <= len(events),
                'Missing, duplicate, late or unordered scoped source evidence')
        for event in scoped:
            require(event['request_id'] == proof['request_id'] and event['url'] == proof['source_url']
                    and event['method'] == 'GET' and event['resource_type'] == 'fetch'
                    and event['is_navigation_request'] is False and event['phase'] == phase
                    and event['same_preview_main_frame'] is True and event['frame_url'] == proof['page_url']
                    and event['request_headers']['range'] is None and event['request_headers']['if-range'] is None,
                    'Source Request/frame/phase or non-range identity differs')
        bridge, response, terminal = scoped[1:]
        require(bridge['source_sha256'] == proof['source_sha256'] and bridge['mimetype'] == 'application/pdf'
                and bridge['byte_length'] == proof['byte_length'] and 0 < bridge['byte_length'] <= 131072
                and bridge['response_headers'] == response['response_headers'], 'Actual preview response differs')
        for event in (bridge, response):
            headers = event['response_headers']
            require(event['status'] == 200 and headers['content-type'] == 'application/pdf'
                    and headers['content-length'] == str(proof['byte_length'])
                    and headers['content-disposition'].startswith('inline;')
                    and all(headers[name] is None for name in ('content-range', 'accept-ranges', 'content-encoding')),
                    'Preview must be the exact complete inline PDF response')
        require(proof['terminal_event'] == terminal['event'] and proof['failure'] == terminal.get('failure'),
                'Terminal proof differs from actual source evidence')
        if terminal['event'] == 'requestfailed':
            require(terminal['failure'] == 'net::ERR_ABORTED', 'Unrecognized preview failure')
            expected_cancellations.append(dict(proof, raw_failure=dict(
                method='GET', url=proof['source_url'], failure='net::ERR_ABORTED')))
        else:
            require(proof['failure'] is None, 'Completed request retains an unexpected failure')
    require(report['verified_invoice_preview_cancellations'] == expected_cancellations,
            'Classified raw failures must equal only the failed verified preview subset')
    require({e['preview_scope_id'] for e in events if e.get('preview_scope_id')} == {p['scope_id'] for p in proofs},
            'Unexpected extra preview scope')


def aggregate(args):
    failures, results = [], []
    try:
        current = verify_sources(args)
        verify_copies(args)
        provenance = json.loads((args.artifacts / 'harness-provenance.json').read_text())
        require(all(provenance[key] == value for key, value in current.items()), 'Harness provenance changed')
    except (AssertionError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        failures.append(dict(id='source-integrity', error_type=type(error).__name__))
    try:
        context = json.loads((args.artifacts / 'invoice-experiment-context.json').read_text())
        require(context == experiment_context(args), 'Experiment context differs from this CI/runtime')
    except (AssertionError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        failures.append(dict(id='experiment-context', error_type=type(error).__name__))
    try:
        ledger = json.loads((args.artifacts / 'scenario-exits.json').read_text())
        require(ledger['application_commit'] == APP_SHA and ledger['validation_commit'] == args.validation_sha,
                'Ledger source mismatch')
        expected_ids = [s['id'] for s in scenarios()]
        require([s['id'] for s in ledger['scenarios']] == expected_ids, 'Missing or duplicate execution entries')
        executions = {s['id']: s for s in ledger['scenarios']}
    except (AssertionError, OSError, ValueError, KeyError, TypeError) as error:
        executions = {}
        failures.append(dict(id='execution-ledger', error_type=type(error).__name__))
    for scenario in scenarios():
        item = dict(id=scenario['id'], report=str(Path(scenario['folder']) / 'browser-result.json'), passed=False)
        try:
            execution = executions[scenario['id']]
            require(all(execution[key] == value for key, value in scenario.items()), 'Execution scenario mismatch')
            item['exit_code'] = execution['exit_code']
            require(execution['execution'] == 'FINISHED' and execution['exit_code'] == 0, 'Scenario failed or never finished')
            report = json.loads((args.artifacts / item['report']).read_text())
            validate_report(report, scenario)
            screenshots = []
            for width in (1440, 390, 320):
                for stage in ('maintenance-tab', 'maintenance-record'):
                    for suffix in ('', '-visible', '-visible-bottom'):
                        path = args.artifacts / scenario['folder'] / f'invoice-preview-{stage}-{width}{suffix}.png'
                        require(path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'), 'Required preview screenshot missing')
                        screenshots.append(dict(path=str(path.relative_to(args.artifacts)), **identity(path)))
            item.update(passed=True, report_status=report['status'], preview_screenshots=screenshots,
                        verified_preview_count=len(report['verified_invoice_preview_fetches']),
                        classified_preview_cancellation_count=len(report['verified_invoice_preview_cancellations']))
        except (AssertionError, OSError, ValueError, KeyError, TypeError) as error:
            item['error_type'] = type(error).__name__
            failures.append(dict(id=item['id'], error_type=type(error).__name__))
        results.append(item)
    prior = None
    try:
        prior = prior_evidence(args)
    except (AssertionError, OSError, ValueError, KeyError, TypeError) as error:
        failures.append(dict(id='prior-evidence-reference', error_type=type(error).__name__))
    summary = dict(
        status='PASS' if not failures else 'FAILED_OR_INCOMPLETE',
        verification_kind='supplemental_separate_fixture_harness_not_original_pr_ci',
        application_commit=APP_SHA, application_tree=APP_TREE, validation_commit=args.validation_sha,
        http_required=0, browser_required=1,
        http_passed=0, browser_passed=sum(r['passed'] for r in results),
        current_run_scope=list(CURRENT_CASES),
        invoice_native_http_experiment=True, invoice_download_cause_confirmed=False,
        diagnostic_only=False, current_run_mode='full_invoice_browser_acceptance',
        native_download_reexecution_required=True,
        required_invoice_previews=6, required_preview_screenshots=18,
        required_native_downloads=3, abort_caller_proven=False,
        previous_results_not_counted_as_current_run=True,
        prior_evidence_index_sha256=PRIOR_INDEX_SHA256,
        prior_evidence_reference=prior,
        source_unchanged=not any(f['id'] == 'source-integrity' for f in failures),
        scenarios=results, failures=failures,
        earlier_node_comparison_dashboard_run=43043343085,
        earlier_node_comparison_dashboard_rerun=False,
        prior_successful_cases_rerun=False,
        prior_failed_browser_cases_reexecuted=list(CURRENT_CASES),
        earlier_results_not_part_of_this_pass=True,
        original_ci_still_requires_separate_status_reporting=True,
        all_original_workflows_replaced=False, native_http_redirect_browser_coverage=False,
        finished_utc=now())
    write_json(args.artifacts / 'remaining-summary.json', summary)
    print(json.dumps(summary, indent=2))
    return 0 if not failures else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'run', 'aggregate'))
    for name in ('application', 'validation', 'artifacts'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--validation-sha', required=True)
    parser.add_argument('--python', type=Path)
    parser.add_argument('--chromium', type=Path)
    args = parser.parse_args()
    for name in ('application', 'validation', 'artifacts'):
        setattr(args, name, getattr(args, name).resolve())
    require(not args.artifacts.is_relative_to(args.application)
            and not args.artifacts.is_relative_to(args.validation), 'Artifacts must be outside both checkouts')
    args.artifacts.mkdir(parents=True, exist_ok=True)
    return {'prepare': prepare, 'run': run, 'aggregate': aggregate}[args.phase](args)


if __name__ == '__main__':
    raise SystemExit(main())
