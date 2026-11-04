"""Seal only after Linux PostgreSQL, Windows render, and Windows source-client acceptance pass."""
import hashlib,json,pathlib,subprocess,shutil
from verify_client_evidence import validate_client
root=pathlib.Path('worlex-scoped-restore-20261104')
linux=pathlib.Path('linux-evidence')
windows=pathlib.Path('windows-evidence')
def require(value, message):
    if not value: raise SystemExit(message)
policy=json.loads((linux/'provisional-policy.json').read_text())
summary=json.loads((windows/'summary.json').read_text())
require(not policy.get('postgres_acceptance_passed') and not policy.get('windows_render_acceptance_passed'), 'Provisional policy unexpectedly executable')
require(summary['passed'] and summary['actual_windows'] and summary['original_failure_reproduced'], 'Windows reproduction missing')
require(summary['candidate']['ok'] and summary['candidate_environment_isolated'] and summary['candidate']['parsed_rows_verified'], 'Windows candidate invalid')
sha=hashlib.sha256((root/'worlex_restore.py').read_bytes()).hexdigest()
require(summary['candidate']['runner_sha256']==sha==policy['tested_artifacts']['worlex_restore.py'], 'Runner hash mismatch')
commit=subprocess.run(['git','rev-parse','HEAD'],check=True,capture_output=True,text=True).stdout.strip()
require(summary['candidate_commit']==commit==(linux/'commit.txt').read_text().strip(), 'Acceptance commit mismatch')
acceptance=policy['acceptance_summary']
require(acceptance['postgres_required'] and acceptance['expected']>=71, 'Mandatory PostgreSQL suite absent')
require(acceptance['run']==acceptance['expected'] and not any(acceptance[k] for k in ('failures','errors','skipped')), 'Linux tests incomplete')
coverage=json.loads((linux/'full-fixture-coverage.json').read_text())
require(coverage==policy.get('full_table_acceptance'), 'Full-table evidence differs from Linux policy')
require(coverage.get('synthetic_only') is True and coverage.get('source_rows')==4100 and coverage.get('populated_tables')==37, 'Full 37-table synthetic fixture missing')
require(coverage.get('source_counts')==json.loads((root/'source-counts.json').read_text()), 'Full-table cardinalities differ')
require(all(coverage.get(k) is True for k in ('imported_values_and_blobs_match','preserved_rows_match','owner_bindings_quarantined')), 'Full-table preservation checks missing')
before=json.loads((linux/'disconnect-before-commit.json').read_text())
after=json.loads((linux/'disconnect-after-commit.json').read_text())
require(policy.get('disconnect_acceptance')=={'before_commit':before,'after_commit':after}, 'Disconnect evidence differs from Linux policy')
for item in (before,after):
    require(item.get('synthetic_only') is True and item.get('source_rows')==4100 and item.get('populated_tables')==37, 'Full-table disconnect evidence missing')
require(all(before.get(k) is True for k in ('actual_connection_closed_before_commit','all_imports_absent','preserved_rows_match','sequences_unchanged','fresh_readonly_verification_rejects_absent_restore')) and before.get('restore_retried') is False, 'Pre-commit rollback proof missing')
require(all(after.get(k) is True for k in ('real_commit_then_client_error','fresh_readonly_verification_matches','preserved_rows_match','replay_guard_rejected_before_insert','sequences_unchanged_by_replay')) and after.get('network_packet_loss_reproduced') is False, 'Post-commit reconciliation proof missing')
for relative, expected in policy['tested_artifacts'].items():
    require(hashlib.sha256((root/relative).read_bytes()).hexdigest()==expected, 'Artifact mismatch: '+relative)
client_dir=pathlib.Path('windows-client-evidence')
client=json.loads((client_dir/'client-proof.json').read_text())
client_policy=json.loads((client_dir/'provisional-policy.json').read_text())
require(client_policy['tested_artifacts']==policy['tested_artifacts'], 'Windows provisional artifact map mismatch')
require(client_policy['postgres_structure_sha256']==policy['postgres_structure_sha256'], 'Linux/Windows catalog structure differs')
require((client_dir/'commit.txt').read_text().strip()==commit, 'Windows client commit evidence mismatch')
for filename,key in [('full-fixture-coverage.json','full_table_acceptance'),('summary.json','acceptance_summary')]:
    require(json.loads((client_dir/filename).read_text())==client[key], 'Windows standalone evidence mismatch: '+filename)
for filename,key in [('disconnect-before-commit.json','before_commit'),('disconnect-after-commit.json','after_commit')]:
    require(json.loads((client_dir/filename).read_text())==client['disconnect_acceptance'][key], 'Windows standalone disconnect mismatch')
profile=validate_client(client,policy,root,client_dir,commit)
sidecar=json.loads((client_dir/'sidecar-proof.json').read_text())
require(client.get('sidecar')==sidecar and sidecar.get('actual_windows') is True and all(sidecar.get(k) is True for k in ('production_guard_passed','core_preconnection_guard_passed','isolated_bootstrap_passed')) and sidecar.get('sidecar_wheel_sha256')==client['wheel']['sha256'], 'Actual production sidecar guard proof missing')
policy['windows_client_acceptance_passed']=True
policy['windows_client_acceptance']=profile
policy['postgres_acceptance_passed']=True
policy['windows_render_acceptance_passed']=True
policy['windows_acceptance_summary']=summary
policy['tested_commit']=commit
require(policy['workflow_sha256']==hashlib.sha256(pathlib.Path('.github/workflows/worlex-restore-postgres.yml').read_bytes()).hexdigest(), 'Workflow hash mismatch')
out=pathlib.Path('combined-evidence');out.mkdir()
(out/'sealed-policy.json').write_text(json.dumps(policy,indent=2,sort_keys=True))
(out/'disconnect-before-commit.json').write_text(json.dumps(before,indent=2,sort_keys=True))
(out/'disconnect-after-commit.json').write_text(json.dumps(after,indent=2,sort_keys=True))
(out/'full-fixture-coverage.json').write_text(json.dumps(coverage,indent=2,sort_keys=True))
(out/'tested-code-sha256.json').write_text(json.dumps(policy['tested_artifacts'],indent=2,sort_keys=True))
shutil.copyfile(client_dir/client['wheel']['filename'],out/client['wheel']['filename'])
shutil.copyfile(client_dir/'client-proof.json',out/'windows-client-proof.json')
print('All three mandatory gates passed for identical code; combined policy sealed')
