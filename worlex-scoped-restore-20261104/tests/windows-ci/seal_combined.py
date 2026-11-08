"""Seal only after Linux PostgreSQL, Windows render, and Windows pure-client gates."""
import json
from pathlib import Path, PureWindowsPath
import shutil
import subprocess

from verify_client_evidence import (artifact_path, safe_relative, sha, validate_client,
                                    validate_imported_modules, validate_ssl_runtime, validate_restore_scope,
                                    validate_acceptance, validate_acceptance_artifacts)


def require(value, message):
    if not value:
        raise ValueError(message)


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON evidence key: ' + key)
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON evidence')))


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding='utf-8')


def main():
    root = Path('worlex-scoped-restore-20261104')
    linux, windows, client_dir = map(Path, ('linux-evidence', 'windows-evidence', 'windows-client-evidence'))
    policy = read_json(linux / 'provisional-policy.json')
    summary = read_json(windows / 'summary.json')
    require(not any(policy.get(key) for key in ('postgres_acceptance_passed',
                'windows_render_acceptance_passed', 'windows_client_acceptance_passed')),
            'Provisional policy unexpectedly executable')
    require(summary.get('passed') is True and summary.get('actual_windows') is True and
            summary.get('original_failure_reproduced') is True, 'Windows reproduction missing')
    candidate = summary['candidate']
    require(candidate.get('ok') is True and summary.get('candidate_environment_isolated') is True and
            candidate.get('parsed_rows_verified') is True, 'Windows candidate invalid')
    require(candidate['runner_sha256'] == sha(root / 'worlex_restore.py') ==
            policy['tested_artifacts']['worlex_restore.py'], 'Runner hash mismatch')
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
    require(summary['candidate_commit'] == commit == (linux / 'commit.txt').read_text().strip(),
            'Acceptance commit mismatch')
    acceptance = policy['acceptance_summary']
    validate_acceptance(acceptance)
    validate_acceptance_artifacts(policy['tested_artifacts'], root)
    require(read_json(linux / 'summary.json') == acceptance, 'Standalone Linux summary differs')
    require(read_json(linux / 'tested-code-sha256.json') == policy['tested_artifacts'],
            'Standalone Linux code map differs')
    coverage = read_json(linux / 'full-fixture-coverage.json')
    validate_restore_scope(coverage, read_json(root / 'source-counts.json'))
    require(coverage == policy.get('full_table_acceptance'), 'Full-table evidence differs from Linux policy')
    require(coverage.get('synthetic_only') is True and coverage.get('source_rows') == 4100 and
            coverage.get('populated_tables') == 37, 'Full 37-table synthetic fixture missing')
    require(coverage.get('source_counts') == read_json(root / 'source-counts.json'),
            'Full-table cardinalities differ')
    require(all(coverage.get(key) is True for key in ('imported_values_and_blobs_match',
                'preserved_rows_match', 'owner_bindings_quarantined')), 'Full-table preservation checks missing')
    before = read_json(linux / 'disconnect-before-commit.json')
    after = read_json(linux / 'disconnect-after-commit.json')
    require(policy.get('disconnect_acceptance') == {'before_commit': before, 'after_commit': after},
            'Disconnect evidence differs from Linux policy')
    for item in (before, after):
        validate_restore_scope(item, read_json(root / 'source-counts.json'))
        require(item.get('synthetic_only') is True and item.get('source_rows') == 4100 and
                item.get('populated_tables') == 37, 'Full-table disconnect evidence missing')
    require(all(before.get(key) is True for key in ('actual_connection_closed_before_commit',
                'all_imports_absent', 'preserved_rows_match', 'sequences_unchanged',
                'fresh_readonly_verification_rejects_absent_restore')) and before.get('restore_retried') is False,
            'Pre-commit rollback proof missing')
    require(all(after.get(key) is True for key in ('real_commit_then_client_error',
                'fresh_readonly_verification_matches', 'preserved_rows_match',
                'replay_guard_rejected_before_insert', 'sequences_unchanged_by_replay')) and
            after.get('network_packet_loss_reproduced') is False, 'Post-commit reconciliation proof missing')
    for relative, expected in policy['tested_artifacts'].items():
        safe_relative(relative)
        path = root / relative
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()) and
                sha(path) == expected, 'Artifact mismatch: ' + relative)
    client = read_json(client_dir / 'client-proof.json')
    client_policy = read_json(client_dir / 'provisional-policy.json')
    require(not any(client_policy.get(key) for key in ('postgres_acceptance_passed',
                'windows_render_acceptance_passed', 'windows_client_acceptance_passed')),
            'Windows provisional policy unexpectedly executable')
    require(client_policy['tested_artifacts'] == policy['tested_artifacts'],
            'Windows provisional artifact map mismatch')
    require(read_json(client_dir / 'tested-code-sha256.json') == policy['tested_artifacts'],
            'Standalone Windows code map mismatch')
    require(client_policy['postgres_structure_sha256'] == policy['postgres_structure_sha256'],
            'Linux/Windows catalog structure differs')
    require((client_dir / 'commit.txt').read_text().strip() == commit, 'Windows client commit evidence mismatch')
    for filename, key in (('full-fixture-coverage.json', 'full_table_acceptance'),
                          ('summary.json', 'acceptance_summary'), ('build-proof.json', 'build_proof'),
                          ('stability-proof.json', 'stability')):
        require(read_json(client_dir / filename) == client[key],
                'Windows standalone evidence mismatch: ' + filename)
    for filename, key in (('disconnect-before-commit.json', 'before_commit'),
                          ('disconnect-after-commit.json', 'after_commit')):
        require(read_json(client_dir / filename) == client['disconnect_acceptance'][key],
                'Windows standalone disconnect mismatch')
    require(client_policy['acceptance_summary'] == client['acceptance_summary'] and
            client_policy['full_table_acceptance'] == client['full_table_acceptance'] and
            client_policy['disconnect_acceptance'] == client['disconnect_acceptance'] and
            client_policy['workflow_sha256'] == client['workflow_sha256'],
            'Windows provisional acceptance proof differs')
    runtime = read_json(client_dir / 'runtime-proof.json')
    for key in ('wheels', 'wheel_files', 'imported_modules', 'ssl_runtime', 'tls'):
        require(runtime[key] == client[key], 'Standalone Windows runtime proof differs: ' + key)
    require(runtime.get('owned_server_directory_verified') is True, 'Owned synthetic fixture proof missing')
    profile = validate_client(client, policy, root, client_dir, commit)
    sidecar = read_json(client_dir / 'sidecar-proof.json')
    require(client.get('sidecar') == sidecar and sidecar.get('actual_windows') is True and
            all(sidecar.get(key) is True for key in ('production_guard_passed', 'core_preconnection_guard_passed',
                                                   'isolated_bootstrap_passed')) and
            sidecar.get('sidecar_wheels_sha256') == {name: value['sha256'] for name, value in profile['wheels'].items()},
            'Actual production sidecar guard/bootstrap proof missing')
    result = sidecar['result']
    require(result.get('client_profile') == profile['client_profile'] and
            result.get('package_version') == profile['package_version'] and
            result.get('pure_python_client') is True and result.get('tls_context_verified') is True,
            'Production sidecar guard result missing')
    site = validate_imported_modules(result['imported_modules'], profile['wheel_files'])
    require(PureWindowsPath(site).name == 'client-sidecar', 'Production guard did not load the staged sidecar')
    sidecar_runtime = validate_ssl_runtime(result['ssl_runtime'])
    require(sidecar_runtime['python_version'].split()[0] == profile['ssl_runtime']['python_version'].split()[0],
            'Sidecar Python version differs')
    for key in ('python_executable', 'base_prefix', 'system_directory', 'openssl_version', 'ssl_provider', 'openssl_linkage'):
        require(sidecar_runtime[key] == profile['ssl_runtime'][key], 'Sidecar Python SSL runtime differs: ' + key)
    expected_modules = {module['name'].casefold(): module for module in profile['ssl_runtime']['loaded_modules']}
    for prefix in ('_ssl.pyd', 'python312.dll', 'libssl', 'libcrypto'):
        expected = [value for name, value in expected_modules.items() if name.startswith(prefix)]
        actual = [value for value in sidecar_runtime['loaded_modules'] if value['name'].casefold().startswith(prefix)]
        require(len(expected) == len(actual) == 1 and actual == expected,
                'Sidecar required Python SSL module evidence differs: ' + prefix)
    for module in sidecar_runtime['loaded_modules']:
        name = module['name'].casefold()
        if name in expected_modules:
            require(expected_modules[name] == module,
                    'Sidecar actual Python SSL module evidence differs')
    require(policy['workflow_sha256'] == sha(Path('.github/workflows/worlex-restore-postgres.yml')),
            'Workflow hash mismatch')
    policy.update(windows_client_acceptance_passed=True, windows_client_acceptance=profile,
                  postgres_acceptance_passed=True, windows_render_acceptance_passed=True,
                  windows_acceptance_summary=summary, tested_commit=commit)
    out = Path('combined-evidence')
    out.mkdir()  # Never overwrite or reuse an earlier seal.
    pure_out = out / 'pure-wheels'
    pure_out.mkdir()
    for filename, wheel in profile['wheels'].items():
        target = pure_out / filename
        shutil.copyfile(artifact_path(client_dir / 'pure-wheels', filename), target)
        require(sha(target) == wheel['sha256'], 'Copied sealed wheel differs: ' + filename)
    app_out = out / 'application-wheels'
    app_out.mkdir()
    for app in client['build_proof']['application_source_wheels']:
        target = app_out / app['wheel_filename']
        shutil.copyfile(artifact_path(client_dir / 'application-wheels', app['wheel_filename']), target)
        require(sha(target) == app['wheel_sha256'], 'Copied application wheel differs')
    for filename in ('client-proof.json', 'sidecar-proof.json', 'runtime-proof.json',
                     'stability-proof.json', 'build-proof.json'):
        shutil.copyfile(client_dir / filename, out / ('windows-' + filename))
    write_json(out / 'disconnect-before-commit.json', before)
    write_json(out / 'disconnect-after-commit.json', after)
    write_json(out / 'full-fixture-coverage.json', coverage)
    write_json(out / 'tested-code-sha256.json', policy['tested_artifacts'])
    # Emit the executable seal only after all gates and copied artifacts pass.
    write_json(out / 'sealed-policy.json', policy)
    print('All three mandatory gates passed for identical code; pure-client combined policy sealed')


if __name__ == '__main__':
    main()
