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
