"""Check this one Render deployment environment; no network and no secrets."""
import argparse
from collections import Counter
from importlib import metadata
import json
from pathlib import Path
import platform
import re
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--expected',type=Path,default=Path(__file__).with_name('expected-render-py314-linux-x86_64.json'))
parser.add_argument('--pre',action='store_true',help='Check interpreter and platform only before pip install')
args=parser.parse_args()
data=json.loads(args.expected.read_text())
expected_env=(data['implementation'],data['python'],data['os'],data['arch'])
seen_env=(platform.python_implementation(),platform.python_version(),platform.system(),platform.machine())
if seen_env!=expected_env:
 raise SystemExit(f'Render lock target mismatch: expected {expected_env}, found {seen_env}')
if args.pre:
 print('Render lock environment validated')
 sys.exit(0)
canonical=lambda s:re.sub(r'[-_.]+','-',s).lower()
direct=data['direct'];transitive=data['transitive'];assert not direct.keys() & transitive.keys()
want={**direct,**transitive}
duplicates=Counter()
seen={}
# These are build bootstrapping tools, separate from application dependency/runtime pin matrix.
bootstrap={'pip','setuptools','wheel'}
for d in metadata.distributions():
 name=canonical(d.metadata['Name'])
 if name in bootstrap:continue
 duplicates[name]+=1
 seen[name]=d.version
missing=sorted(want.keys()-seen.keys());extra=sorted(seen.keys()-want.keys())
changed=sorted((n,want[n],seen[n]) for n in want.keys() & seen.keys() if want[n]!=seen[n])
duplicate=sorted(n for n in duplicates if duplicates[n]>1)
if missing or extra or changed or duplicate:
 raise SystemExit(f'Render dependency mismatch: missing={missing} extra={extra} changed={changed} duplicates={duplicate}')
print(f'Render lock exact: direct={len(direct)}, transitive={len(transitive)}, python={seen_env[1]}')
