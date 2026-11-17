import sys,json,hashlib
from pathlib import Path
r=Path(sys.argv[1]);m=json.loads((r/'tests/demo_previous_day_browser/manifest.json').read_text())
for name,expected in {**m['files'],**m['products']}.items():
 assert hashlib.sha256((r/name).read_bytes()).hexdigest()==expected,name
print('TEST_AND_PATCHED_PRODUCT_HASHES_MATCH')
