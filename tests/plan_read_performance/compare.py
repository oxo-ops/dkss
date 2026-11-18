"""Compare synthetic API results, query/write counts, and observed latency."""
import json,sys,statistics
from pathlib import Path
before,after=(json.loads(Path(p).read_text()) for p in sys.argv[1:3])
assert before['fixture']==after['fixture']
for key in ('sha','rows','bytes','queries','writes'):
 assert {s[key] for s in before['samples']} == {s[key] for s in after['samples']},key
assert all(s['writes']==0 for s in before['samples']+after['samples'])
b=statistics.median(s['ms'] for s in before['samples']);a=statistics.median(s['ms'] for s in after['samples'])
print(json.dumps({'identical_json':True,'no_writes':True,'before_median_ms':b,'after_median_ms':a,'observed_reduction_percent':round((b-a)/b*100,1)},indent=2))
# Timings are observations, not a flaky wall-clock correctness gate.
