# M06 provenance query reduction

Base: `2f769d5407a9165b7dcd9024a69955ec160fee97` (#351 merged).

Synthetic Windows SQLite measurement: 100 and 1000 vehicles, each with one
confirmed legacy periodic original, record and next plan; one additional
unconfirmed plan. New temporary database only, external sockets blocked, fake
OCR fixture. These are hypothetical sizes, not production fleet counts or SLAs.
Single observations; wall time varies with local load. Query counts are the
stronger evidence. Existing plan and record fields remained unchanged.

| Rows | Route | Queries before / after | Seconds before / after |
|---|---|---|---|
|100|Annual API|1922 / 317|1.144 / 0.224|
|100|Unread-count GET|4033 / 3233|1.394 / 1.038|
|100|Excel|1922 / 317|1.696 / 0.635|
|1000|Annual API|19022 / 3017|15.558 / 3.315|
|1000|Unread-count GET|40177 / 32177|12.150 / 10.271|
|1000|Excel|19022 / 3017|24.633 / 9.085|

The annual loop previously resolved every saved plan for every display kind,
then resolved the selected plan again for serialization. A confirmed record
also fetched its original twice within one plan resolution. The change groups
plans once by resolved kind within the read operation and reuses that exact
value for serialization. Summary also reuses its operation-local resolution.
No global/request cache, schema changes, stored reclassification, or new rules.
Subsequent requests still read updated original evidence.

The new query-bound regression failed before (13 original reads against a bound
of 3) and passed after; it also changes the original status and verifies the
next request becomes unconfirmed while preserving raw legacy values. Targeted
regressions: 24 passed (44.323s), covering completion evidence, rescheduling,
company/vehicle boundaries, held receipts and ended-notice reissue protection.

Limits: notification processing still has per-vehicle queries; this is not a
general batching rewrite or production performance acceptance. SQLite timing
does not predict PostgreSQL/network latency. Login and real OCR recovery are
not tested or claimed. No production operation or deployment performed.

## Follow-up: request-local repeated classification

At intermediate head 5c0d90a, the 32,177 notification statements break down as:
original reads from record_kind 10,000; source-record reads from plan_kind
8,000; has_actual record/execution reads 2,000 each; expiry planned/dependency
plan reads 1,000 each; dependency record/execution reads 1,000 each; receipt
SELECT/DML and remaining bookkeeping 6,177. Audit reads total two, not dominant.
Call-site profiling counts SQL operations, including autoflush writes; it does
not label every receipt statement as a redundant SELECT.

Only the repeated classification was changed. Results are held in the current
request's environ, keyed by function, scoped ORM object, company and vehicle.
Unflushed evidence edits bypass/clear the cache. Evidence flush, commit,
rollback and Session bulk/text writes invalidate it. No cross-request cache,
unbounded cross-company fetch, or change to authorization/notification rules.

| Rows | Route | Final SQL | Final seconds |
|---|---|---:|---:|
|100|Annual API|217|0.149|
|100|Unread-count GET|1633|0.417|
|100|Excel|217|0.507|
|1000|Annual API|2017|2.114|
|1000|Unread-count GET|16177|3.896|
|1000|Excel|2017|6.977|

The same script, fixture, endpoints and Windows environment as the initial
table were used. Each endpoint is sampled once per fresh fixture, in order
annual / unread-count / Excel; there is no dedicated warm-up and no median,
variance or percentile claim. OS/library caches and concurrent local test load
can affect timing. First notification polling includes normal creation writes.
These limitations apply to all before/intermediate/final timings.

Additional tests: 11 passed, including the existing eight notice contracts with
request caching enabled; same-request unflushed/flush/rollback/ORM bulk/text SQL/
commit changes; company/vehicle/original separation. An additional focused 16
tests passed. Final full CI must be read at the final head, not 5c0d90a.

Remaining per-vehicle actual/expiry queries and receipt processing are a separate
follow-up, not an open-ended rewrite in this PR. Batch fetching could reduce
those reads, but changing receipt processing is outside the measured repeated
classification fix. No observed correctness failure blocks this bounded change;
production capacity, dense per-vehicle history and warm-load distributions remain
unmeasured rather than being declared release blockers.
