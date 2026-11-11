#!/usr/bin/env python3
"""Run only the remaining PR377 cases; never modify the frozen application."""
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
FIXED_HELPER_BLOB = 'f3df79a596a9ad2e7f9bb3dd719f659c5187abce'
VALIDATION_FILES = {
    '.github/workflows/pr377-supplemental-browser.yml', 'README.md',
    'harness/confirmation_acceptance.py', 'harness/validate_remaining.py',
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
    'tests/video_connected_browser/acceptance.py',
    'tests/video_connected_browser/run-isolated.sh',
    'tests/history_presentation_browser/guard/sitecustomize.py',
)
CONFIRMATIONS = ('confirmation_manufacturer', 'confirmation_legal', 'confirmation_progression')
CONNECTED = ('normal', 'instruction', 'recheck', 'invoice', 'periodic_instruction', 'periodic_timing')


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
            'Confirmation helper differs from the reviewed fixture-only correction')
    return dict(application_commit=APP_SHA, application_tree=APP_TREE,
                validation_commit=args.validation_sha,
                validation_tree=git(validation, 'rev-parse', 'HEAD^{tree}'),
                frozen_files=files, validation_files=validation_files)


def harness_root(args):
    return args.artifacts.parent / 'pr377-confirmation-harness'


def verify_copies(args):
    target = harness_root(args)
    for relative in COPIES:
        require((target / relative).read_bytes() == (args.application / relative).read_bytes(),
                'Copied original harness/guard changed: ' + relative)
    require((target / 'tests/video_connected_browser/confirmation_acceptance.py').read_bytes()
            == (args.validation / 'harness/confirmation_acceptance.py').read_bytes(),
            'Separate confirmation helper changed')
    # The unchanged acceptance.py prepends app/ and app/tests/ to sys.path.
    # Neither may shadow the validation-side helper in the script directory.
    for directory in (args.application, args.application / 'tests',
                      target / 'tests/history_presentation_browser/guard'):
        require(not (directory / 'confirmation_acceptance.py').exists()
                and not (directory / 'confirmation_acceptance').exists(), 'Ambiguous helper import')


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
    destination = target / 'tests/video_connected_browser/confirmation_acceptance.py'
    shutil.copyfile(args.validation / 'harness/confirmation_acceptance.py', destination)
    verify_copies(args)
    manifest.update(
        verification_kind='supplemental_separate_fixture_harness_not_original_pr_ci',
        copied_original_files=list(COPIES),
        helper_application_path='tests/video_connected_browser/confirmation_acceptance.py',
        helper_validation_path='harness/confirmation_acceptance.py',
        executed_helper_path=str(destination),
        application_checkout_modified=False,
        prepared_utc=now())
    write_json(args.artifacts / 'harness-provenance.json', manifest)


def scenarios():
    result = []
    for case in CONFIRMATIONS:
        result.append(dict(id='http-' + case, folder='connected-' + case + '-preflight',
                           family='confirmation', case=case, browser=False))
    result.append(dict(id='browser-common', folder='.', family='common', case=None, browser=True))
    for case in ('instruction', 'recheck', 'timing'):
        result.append(dict(id='browser-stage2-' + case, folder=case, family='stage2', case=case, browser=True))
    for case in CONNECTED + CONFIRMATIONS:
        result.append(dict(id='browser-connected-' + case, folder='connected-' + case,
                           family='confirmation' if case in CONFIRMATIONS else 'connected',
                           case=case, browser=True))
    return result


def command(args, scenario):
    family = scenario['family']
    scripts = {
        'common': args.application / 'tests/common_priority_browser/run-isolated.sh',
        'stage2': args.application / 'tests/common_priority_browser/run-stage2-isolated.sh',
        'connected': args.application / 'tests/video_connected_browser/run-isolated.sh',
        'confirmation': harness_root(args) / 'tests/video_connected_browser/run-isolated.sh',
    }
    value = ['bash', str(scripts[family]), str(args.application), str(args.python), '--expected-sha', APP_SHA]
    if scenario['case']:
        value += ['--case', scenario['case']]
    value += ['--run-browser', '--chromium', str(args.chromium)] if scenario['browser'] else ['--preflight-only']
    return value


def run(args):
    require(args.python and args.python.is_file() and os.access(args.python, os.X_OK), 'Executable Python required')
    require(args.chromium and args.chromium.is_file() and os.access(args.chromium, os.X_OK), 'Executable Chromium required')
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
            item.update(passed=True, report_status=report['status'])
        except (AssertionError, OSError, ValueError, KeyError, TypeError) as error:
            item['error_type'] = type(error).__name__
            failures.append(dict(id=item['id'], error_type=type(error).__name__))
        results.append(item)
    summary = dict(
        status='PASS' if not failures else 'FAILED_OR_INCOMPLETE',
        verification_kind='supplemental_separate_fixture_harness_not_original_pr_ci',
        application_commit=APP_SHA, application_tree=APP_TREE, validation_commit=args.validation_sha,
        http_required=3, browser_required=13,
        http_passed=sum(r['passed'] for r in results[:3]), browser_passed=sum(r['passed'] for r in results[3:]),
        source_unchanged=not any(f['id'] == 'source-integrity' for f in failures),
        scenarios=results, failures=failures,
        earlier_node_comparison_dashboard_run=43043343085,
        earlier_evidence_rerun=False, earlier_results_not_part_of_this_pass=True,
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
