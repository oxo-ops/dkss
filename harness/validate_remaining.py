#!/usr/bin/env python3
"""Collect only bounded PR377 invoice preview evidence; never claim acceptance or modify the frozen application."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

APP_SHA = '30d4dfeee97f69bd00650c6bf56a5ce234f34437'
APP_TREE = '31bb88b2d7a1a93f4c52f5aeefd59e97a8c8d3ea'
FIXED_HELPER_BLOB = '44e1612f2ca59eca80a2c6a436426bc722af18a7'
FIXED_ACCEPTANCE_BLOB = '7b1ef09ca54fb545c44fb85bf78bfd68f36637b2'
RECEIVER_BLOB = 'e84e269a1f72e9772bd33284024601f31644d1c0'
CONTAINER_IMAGE = 'mcr.microsoft.com/playwright/python@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d'
PDF_NAVIGATION_BLOB = '4573aa6f07666f1d4e508b7352cc4cd42df0a323'
PRIOR_INDEX_SHA256 = '9c313472fcfe008ba25bbe49d43843c87fb064253dfcfc46c4d2af93e8d1fe30'
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
            'Acceptance entry point differs from the reviewed preview observation helper')
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
    return args.artifacts.parent / 'pr377-invoice-preview-harness'


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
        verification_kind='supplemental_preview_diagnostic_not_invoice_acceptance_or_original_pr_ci',
        copied_original_files=list(COPIES),
        modified_external_helpers=[dict(application_path='tests/video_connected_browser/' + name,
                                        validation_path='harness/' + name,
                                        executed_path=str(target / 'tests/video_connected_browser' / name))
                                   for name in ('acceptance.py',)],
        retained_unexecuted_confirmation_helper='harness/confirmation_acceptance.py',
        added_external_helpers=[dict(validation_path='harness/' + name,
                                     executed_path=str(target / 'tests/video_connected_browser' / name))
                                for name in ('native_pdf_navigation.py',)],
        retained_unexecuted_receiver_helper='harness/exact_invoice_download.py',
        prior_evidence_index_sha256=PRIOR_INDEX_SHA256,
        current_run_browser_cases=[],
        current_diagnostic_browser_cases=['invoice-preview-observation'],
        native_download_reexecuted=False, full_invoice_browser_executed=False,
        current_run_http_cases=[],
        application_checkout_modified=False,
        prepared_utc=now())
    write_json(args.artifacts / 'harness-provenance.json', manifest)


def prior_evidence(args):
    path = args.validation / 'harness/prior-evidence.json'
    require(identity(path)['sha256'] == PRIOR_INDEX_SHA256, 'Prior evidence index changed')
    prior = json.loads(path.read_text())
    require(prior['application_commit'] == APP_SHA and prior['application_tree'] == APP_TREE,
            'Prior evidence application mismatch')
    require(prior['run_id'] == 43066261383 and prior['artifact_id'] == 13876665717,
            'Wrong previous evidence run')
    require(prior['http_passed'] == 0 and prior['browser_passed'] == 0 and prior['source_unchanged'] is True,
            'Prior pass counts or source status changed')
    require(prior['overall_status'] == 'FAILED_OR_INCOMPLETE', 'Prior failure must not be relabeled')
    previous = prior['previous_evidence_reference']
    require(previous['run_id'] == 43061389706 and previous['http_passed'] == 0
            and previous['browser_passed'] == 1 and previous['overall_status'] == 'FAILED_OR_INCOMPLETE',
            'Earlier run hierarchy must remain intact')
    require(len(prior['scenarios']) == 1 and prior['scenarios'][0]['id'] == 'browser-connected-invoice'
            and prior['scenarios'][0]['passed'] is False, 'Latest invoice failure must remain separate')
    return prior


def scenarios():
    return [dict(id='diagnostic-preview-' + case, folder='preview-' + case,
                 family='external', case=case, browser=True, diagnostic=True) for case in CURRENT_CASES]


def command(args, scenario):
    require(any(all(scenario.get(key) == value for key, value in expected.items())
                for expected in scenarios()), 'No other scenario may execute in this run')
    script = harness_root(args) / 'tests/video_connected_browser/run-isolated.sh'
    return ['bash', str(script), str(args.application), str(args.python), '--expected-sha', APP_SHA,
            '--case', scenario['case'], '--run-browser', '--chromium', str(args.chromium),
            '--invoice-preview-observe-only']


def diagnostic_context(args):
    """Record the requested CI location/selection, not an authorization mechanism."""
    require(os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('GITHUB_REPOSITORY') == 'oxo-ops/dkss'
            and os.environ.get('GITHUB_SHA') == args.validation_sha,
            'This preview-only diagnostic is only selected in the official CI workflow')
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
                browser_case='invoice', cli_flag='--invoice-preview-observe-only',
                diagnostic_scope='1440px actual maintenance tab/record preview disclosures only',
                native_download_reexecuted=False, full_invoice_browser_executed=False,
                wrapper_and_audit_guard_unchanged=True, native_pdf_helper_unchanged=True)


def run(args):
    require(args.python and args.python.is_file() and os.access(args.python, os.X_OK), 'Executable Python required')
    require(args.chromium and args.chromium.is_file() and os.access(args.chromium, os.X_OK), 'Executable Chromium required')
    verify_sources(args)
    verify_copies(args)
    context = diagnostic_context(args)
    context_path = args.artifacts / 'invoice-preview-context.json'
    require(not context_path.exists(), 'Refusing to reuse preview context evidence')
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
    require(report['scenario'] == scenario['case'] == 'invoice', 'Report scenario mismatch')
    require(report['status'] == 'PREVIEW_DIAGNOSTIC_COMPLETE_NOT_ACCEPTANCE'
            and report['browser_acceptance_passed'] is False and report['browser_started'] is True
            and report['diagnostic_only'] is True, 'Report is not completed diagnostic-only evidence')
    require(report['full_invoice_browser_executed'] is False and report['native_download_reexecuted'] is False
            and report['native_invoice_http_experiment'] is False
            and report['protected_records_unchanged'] is True, 'Diagnostic scope/protected-record mismatch')
    for name in ('invoice_downloads', 'invoice_http_transfers', 'original_pdf_navigations', 'invoice_source_navigations'):
        require(report[name] == [], 'Previously exercised native path must not rerun: ' + name)
    observations = report['invoice_preview_observations']
    require([(x['width'], x['stage']) for x in observations]
            == [(1440, 'maintenance-tab'), (1440, 'maintenance-record')], 'Both bounded observations required')
    for observation in observations:
        require(observation['phase'] == 'width:1440/' + observation['stage']
                and observation['present'] is True and observation['disclosure_open'] is True
                and isinstance(observation['ready'], bool) and isinstance(observation['error'], bool)
                and observation['source_base'] and observation['record_key'], 'Incomplete preview DOM evidence')
        require(observation['ready'] or observation['error'] or observation.get('wait_error'),
                'Preview requires ready, error or explicit bounded-wait evidence')
    require(observations[0]['source_base'] == observations[1]['source_base']
            and observations[0]['record_key'] == observations[1]['record_key'], 'Preview source/record changed')
    require(report['previews_ready'] == all(x['ready'] for x in observations), 'Preview readiness summary differs')
    # Errors are diagnostic findings, not a new acceptance exemption. Retain
    # them verbatim in the summary; collection completion is never a PASS.
    for name in ('page_errors', 'blocked_requests', 'failed_gets', 'failed_requests',
                 'invoice_preview_console_errors', 'invoice_source_events'):
        require(isinstance(report[name], list), 'Diagnostic evidence list missing: ' + name)


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
        context = json.loads((args.artifacts / 'invoice-preview-context.json').read_text())
        require(context == diagnostic_context(args), 'Diagnostic context differs from this CI/runtime')
    except (AssertionError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        failures.append(dict(id='diagnostic-context', error_type=type(error).__name__))
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
        item = dict(id=scenario['id'], report=str(Path(scenario['folder']) / 'browser-result.json'), collection_completed=False)
        try:
            execution = executions[scenario['id']]
            require(all(execution[key] == value for key, value in scenario.items()), 'Execution scenario mismatch')
            item['exit_code'] = execution['exit_code']
            require(execution['execution'] == 'FINISHED' and execution['exit_code'] == 0, 'Scenario failed or never finished')
            report = json.loads((args.artifacts / item['report']).read_text())
            validate_report(report, scenario)
            screenshots = []
            for stage in ('maintenance-tab', 'maintenance-record'):
                path = args.artifacts / scenario['folder'] / ('invoice-preview-' + stage + '-1440.png')
                require(path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'), 'Diagnostic screenshot missing or invalid')
                screenshots.append(dict(path=str(path.relative_to(args.artifacts)), **identity(path)))
            item.update(collection_completed=True, report_status=report['status'], screenshots=screenshots,
                        diagnostic_findings={key: report[key] for key in (
                            'previews_ready', 'invoice_preview_observations', 'invoice_preview_console_errors',
                            'invoice_source_events', 'page_errors', 'blocked_requests', 'failed_gets', 'failed_requests')})
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
        status='PREVIEW_DIAGNOSTIC_COMPLETE_NOT_ACCEPTANCE' if not failures else 'PREVIEW_DIAGNOSTIC_FAILED_OR_INCOMPLETE',
        verification_kind='supplemental_preview_diagnostic_not_invoice_acceptance_or_original_pr_ci',
        application_commit=APP_SHA, application_tree=APP_TREE, validation_commit=args.validation_sha,
        http_required=0, browser_required=0, http_passed=0, browser_passed=0,
        diagnostic_browser_required=1, diagnostic_browser_completed=sum(r['collection_completed'] for r in results),
        current_run_scope=list(CURRENT_CASES),
        diagnostic_only=True, full_invoice_browser_executed=False, native_download_reexecuted=False,
        invoice_native_http_experiment=False, invoice_browser_acceptance_passed=False,
        previous_results_not_counted_as_current_run=True,
        prior_evidence_index_sha256=PRIOR_INDEX_SHA256,
        prior_evidence_reference=prior,
        source_unchanged=not any(f['id'] == 'source-integrity' for f in failures),
        scenarios=results, failures=failures,
        earlier_node_comparison_dashboard_run=43043343085,
        earlier_node_comparison_dashboard_rerun=False,
        prior_successful_cases_rerun=False,
        prior_failed_browser_cases_reexecuted=[],
        current_diagnostic_scope='invoice preview at 1440px, maintenance tab and record only',
        earlier_results_not_part_of_this_diagnostic=True,
        original_ci_still_requires_separate_status_reporting=True,
        all_original_workflows_replaced=False, native_http_redirect_browser_coverage=False,
        finished_utc=now())
    write_json(args.artifacts / 'preview-diagnostic-summary.json', summary)
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
