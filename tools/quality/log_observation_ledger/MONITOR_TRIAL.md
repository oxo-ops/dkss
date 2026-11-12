# Q09 nonproduction connection trial

## Status and purpose

This is an offline integration stage for the existing observation ledger. It
connects a bounded due-time decision, synthetic log recording, one versioned
ledger/outbox bundle, reservation before a simulated send, and a simulated
explicit recipient reply. It is **not a live or scheduled monitor**. Passing
these tests does not prove Render collection, real delivery, or a person's
receipt.

The original eight manifest entries, including the projector, ledger and its
54 tests, remain byte-identical. The new source and tests are separate. No app,
database, feature, identity or production-release file is changed.

## Operating boundaries

- The only built-in source, destination, sender and reply evidence are synthetic.
  Scheduling and sending are off by default. A trial explicitly enables its
  synthetic paths; it does not grant permission for an external message.
- The chosen interval and overlapping window are test configuration, not a
  committed production cadence or a late-arrival guarantee.
- The collector preserves the original unfiltered application-log query/reply
  contract. Page linkage is observed progress, never complete coverage.
  `read_checkpoint` stays null.
- State contains only the existing sanitized observations, fixed enums and
  pseudonymous bindings needed by the trial. Raw log text, original IDs,
  credentials and personal data must not be persisted or sent.
- The authoritative observation state and outbox belong to one versioned bundle.
  A competing version, an uncertain save or a capacity limit must stop the send
  path rather than discard replay-protection records.
- A send reservation must be saved before the sender can run. An alert has at
  most one attempt. Replaying a window, restarting after a reservation, or seeing
  a later classification of the same log record must not rearm it.
- `accepted` is not delivery or human acknowledgment. Uncertain outcomes and
  missing history are not permission to retry. An explicit reply must bind the
  fixed recipient/conversation binding, alert, attempt and payload. A future
  real reply adapter must additionally verify the actual sent message. The synthetic
  provider is a test trust boundary, not proof that a real user replied.
- Local state storage is not a hardened remote multi-user service. Any supported
  private-file path is for a newly created test directory only during CI.
  Initialization is explicit; missing or corrupt existing state stops processing.
  Do not choose a production state directory or silently reset missing state.

The original ledger's `not_scheduled`, `not_attempted_by_ledger` and
`not_sent` statuses stay unchanged. Only the additional synthetic outbox
records simulated transport/arrival/acknowledgment results; it does not rewrite
the original ledger as though a live notification had occurred.

Bounds remain explicit: 100 outbox alerts, 10,000 core log IDs, eight variants
per ID, 100 pages, 4 MiB recorder input and 16 MiB total saved bundle. Reaching a
bound stops processing without evicting replay protection. Operational volume
and retention capacity have not been established.

## Reproduction and evidence

Run the existing `test_log_ledger` suite and the new `test_offline_monitor`
suite through the dedicated PR workflow, from
`tools/quality/log_observation_ledger`. The workflow uses the exact candidate
head/tree, a clean inherited environment, Python's standard library and private
temporary state. It adds no package installation, schedule, secret, production
environment or outbound notification.

The new suite contains 41 test methods (including five-marker subtests); the
original suite contains 54. File CAS cases use real private temporary files,
atomic replacement and fsync. Restart cases create another store object in the
same Python process; crash/unknown-write cases inject failures. Concurrent
senders are tested against the in-memory CAS model. These checks do not simulate
power loss, a fresh process, cross-process file writers or recovering a
transport's receipts after its process has ended.

A later classification of the same receipt remains visible in the ledger but
does not replace the original notification payload or enable another attempt.

The PR records the verified candidate SHA, exact test counts, outcomes and
remaining limits after the official run. Source or documentation by itself is
not evidence that a test ran. Original `tests.log` remains the historical
54-test record, not a result for this new trial.

## What remains before actual monitoring

1. A usable, already-authorized execution and scheduling path. This stage does
   not create or alter an automation and must not reuse the obsolete restoration
   instructions of another task.
2. A trusted adapter for actual Render query/reply results, with verified
   workspace/resource routing, no narrowing severity/text/instance filters,
   bounded pages and explicitly reported incomplete reads.
3. A durable private operational store whose permissions, version conflicts,
   ambiguous outcomes, recovery, capacity and retention have been verified with
   the selected runtime. Neither a mock CAS nor the existence of a Library or
   Pages API proves those guarantees.
4. Approval of the real destination and fixed safe message, followed by a
   supported sender and authenticated reply adapter. Verify scheduled collection,
   transport acceptance, receipt and human acknowledgment separately.
5. Named primary/backup operators, hours and incident handling. Log retention,
   database capacity, worker backlog and backup recovery are separate acceptance
   items, not satisfied by this five-marker trial.

No new service contract, Render Cron, additional credential, notification
subscription, paid runner or production permission is introduced. Existing
platform usage limits still apply; no claim is made that all future operational
usage or AI work is free.
