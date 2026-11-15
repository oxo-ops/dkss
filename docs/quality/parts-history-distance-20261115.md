# Part history: do not invent an interval from uncertain records

Baseline: official main `9377f2a1b6fb25564d403e429a60396fa35c0338`, tree
`159c47dc30b4c09fd792ab15430a438725a70a4d` (local equivalent `ed53c92`).
Quality Word v15 requests consistency between recorded maintenance/parts facts,
history and displayed evidence. Accepted M06/date-quality work is not reopened.

## Finding and bounded change

The parts history table calculated a meter difference even when the previous
replacement date was missing. Missing or reversed meters instead displayed
“no previous record”, despite a previous record being present.

Intervals now require canonical, strictly increasing recorded dates and finite,
nonnegative, nondecreasing meters. Equal readings on different dates retain a
real zero. Missing dates/meters, ambiguous chronology and reversed meters each
show a reason, distinct from genuinely absent prior history. If same-part,
same-date predecessor readings disagree, the later interval is also held rather
than selecting a baseline by row ID. Same-event duplicate invoice lines still
count as one event; equal repeated readings are not conflicts.

Only the parts-history interval projection/text changes. Original dates,
meters, record counts, parts grouping, source links, permissions and filters
remain unchanged. Current-state cards and other analysis panels are outside
this change; this does not certify all historical mileage or live acceptance.
No schema, production data, AI request or notification is changed.

## Verification

Synthetic temporary SQLite route fixtures and pure projection tests cover the
new boundaries, actual rendered reason text, genuine zero, missing prior meter,
conflicting same-day predecessors and duplicate lines. Related import-to-parts
and overview tests are included. No external AI, SMTP or storage is configured.

The current event's inconsistent same-date meters are held too, including two
invoice lines under one maintenance event with different readings. This prevents
reusing the first line's interval for a different current meter.

Local combined result: **30 tests, zero skips, OK in 4.368s** (11 focused,
plus DocumentConnectionTests and OverviewTests). Responsive static JS checks
passed all three groups; architecture inventory and generated schema equality
passed. Actual rendered Flask pages were checked, not physical-device/browser
visual acceptance. Full-suite CI and release are not claimed.
