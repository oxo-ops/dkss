# Q09: inspection reminder error metadata

## Evidence and scope

Reviewed the quality plan's secret-safe logging requirement and existing SMTP/MFA/WebPush logging work against main `9377f2a1b6fb25564d403e429a60396fa35c0338` (tree `159c47dc30b4c09fd792ab15430a438725a70a4d`). The inspection reminder poll hook and CLI had separate `logger.exception` calls that formatted database exceptions including SQL/parameters. Single-run CLI also rethrew the original exception. Existing completed delivery logging work is not being reopened.

Synthetic failure injection reproduced three failing tests before the change. No production data or credentials were inspected. A fixed `INSPECTION_ALERT_FAILED` event now retains only allowlisted mode (`poll`, `command`, `watch`) and category (`database`, `input`, `runtime`, `unexpected`). Exception string, arbitrary exception class name, SQL, parameters, traceback, company/user identity, and document content are not logged by these handlers.

Single-run command still exits unsuccessfully, now using a fixed Click error instead of propagating a private payload. Watch mode still rolls back and proceeds to its next tick. HTTP polling still rolls back the failed reminder transaction while returning the original notifications response. No notification content, recipient, threshold, retry policy, company scope, external delivery, schema, or production setting changes.

## Verification and limits

- Three new real Flask/SQLite boundary tests failed before the fix, then passed.
- Focused run: 53 tests passed (three new plus existing reminder/date tests).
- Final new-test run: five passed after adding category and hostile exception-name/mode checks.
- Failure injection uses synthetic SQL/parameters and an in-memory log capture; watch timing and external delivery are mocked. No real mail, Push, AI, or production access.
- This is handler-level logging hardening, not a new monitor or operational monitoring acceptance. Existing logs are not rewritten. Other error/cleanup boundaries remain outside this narrow change. Full integration CI and deployment are separate.
