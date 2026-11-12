# Render read adapter candidate

This additive candidate is not wired into the synthetic monitor or any scheduler.
It accepts an injected synchronous callable implementing the already-authorized
Render list_logs connector. No API credential, new service, dependency, notification,
database write or deployment is introduced.

The callable receives only workspaceId, resource, type=app, direction=forward,
startTime, endTime and limit. Raw response objects stay transient. Only the
existing ledger's sanitized state/report is returned; all reads remain timestamp
coverage-unverified. Errors and malformed replies stop pagination without copying
exception text. Caller must commit state through its operational private CAS;
this adapter does not perform persistence or notification.

The existing connected Render tool was read once for the fixed authorized Web
service, 2026-11-12 06:27–06:28 UTC. Only response shape was inspected: isError=false,
content text holding JSON with logs, hasMore, nextStartTime and nextEndTime.
No actual log text, provider IDs or credentials were written to these files.
The Python adapter was NOT fed live data: the current tool runtime is asynchronous
JavaScript and does not provide a synchronous Python connector bridge. Do not
copy credentials or raw responses into files/tool arguments to fake that bridge.

Local validation: python -m unittest test_render_read_adapter -v; 10 tests,
0 failures/errors/skips. All five marker families, actual observed wrapper shape,
partial-page failure, cursor stall, bounds, duplicate records, wrong resource,
invalid state, malformed response and private-data canary suppression are covered.
Independent static review found no concrete blocking issue. Remote CI for this
additive candidate has not run; the original 95-test stage is separate evidence.

Next connection choice: use the existing authorized Render connector in its native
runtime with a supported in-memory bridge, or adapt this implementation to that
runtime. Do not replace it with a new credential or production cron silently.
The proposed resource remains the existing DKSS Web, not DB logs or other services.
Operational scheduling, durable store, sender, fixed recipient and authenticated
human reply remain unconfigured. The original synthetic monitor must retain its
synthetic-only labeling and must not be presented as real delivery evidence.
