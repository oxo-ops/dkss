"""Make executable policy ONLY after Linux PostgreSQL and Windows A/B both pass."""
import hashlib,json,pathlib,subprocess
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
require(acceptance['postgres_required'] and acceptance['expected']>=34, 'Mandatory PostgreSQL suite absent')
require(acceptance['run']==acceptance['expected'] and not any(acceptance[k] for k in ('failures','errors','skipped')), 'Linux tests incomplete')
for relative, expected in policy['tested_artifacts'].items():
    require(hashlib.sha256((root/relative).read_bytes()).hexdigest()==expected, 'Artifact mismatch: '+relative)
policy['postgres_acceptance_passed']=True
policy['windows_render_acceptance_passed']=True
policy['windows_acceptance_summary']=summary
policy['tested_commit']=commit
require(policy['workflow_sha256']==hashlib.sha256(pathlib.Path('.github/workflows/worlex-restore-postgres.yml').read_bytes()).hexdigest(), 'Workflow hash mismatch')
out=pathlib.Path('combined-evidence');out.mkdir()
(out/'sealed-policy.json').write_text(json.dumps(policy,indent=2,sort_keys=True))
(out/'tested-code-sha256.json').write_text(json.dumps(policy['tested_artifacts'],indent=2,sort_keys=True))
print('Both mandatory gates passed for identical code; combined policy sealed')
