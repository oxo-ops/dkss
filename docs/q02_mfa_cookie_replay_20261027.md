# Q02-AUTH-04: MFA failure limit across copied session cookies

Baseline: `41a4386225913cac589dc1e99dfb36f6a343bfcb` (main, PR #212).
Plan: QP-20261027 v1.3, Q02 / Q10 (partial).

## Reproduced problem

MFA failure count was stored only in Flask's signed client session. Copying a
valid pending session cookie into five clients before sending wrong codes left
the server challenge valid after five failures: each client carried count zero.
The existing endpoint rate limit remains useful but does not make a client
cookie a persistent five-attempt counter.

This was reproduced with real Flask requests and SQLite, before changing the
application. No production data or user accounts were used.

## Change

- Identify each issued challenge using a SHA-256 fingerprint of its salted hash.
  Bind the pending session to that challenge so a replacement code invalidates
  old pending sessions.
- Count failed attempts from existing `AuditLog` events, scoped by company,
  username, event type, target and the exact challenge fingerprint. Neither the
  raw OTP nor its password hash is added to the audit detail.
- Acquire the user row with `FOR UPDATE` on MFA POST and refresh ORM state.
  Persist the failure event and fifth-attempt invalidation in one transaction.
- Keep existing code lifetime, resend delay, account checks and rate limiting.

No table, column or migration is introduced. A pending MFA session created before
this change must restart login (the existing 60-second resend delay may apply).
Already authenticated sessions are not intentionally invalidated by this change.
No product UI, date validation, production DB audit or driving report UI is changed.

The failure counter now depends on retaining MFA failure audit events while the
challenge is valid. Existing cleanup retains events for 365 days; challenge
lifetime is 10 minutes. If retention or audit storage changes, preserve this
invariant or introduce a dedicated persisted challenge counter.

## Validation

- 15 MFA tests, including copied cookies, single use, expiry, account lock,
  company disable, password change, wrong password, mail failure, resend delay,
  new challenge binding, challenge reset and separate companies with same ID.
- 68 Q02 tests in one process: passed (36.123 seconds).
- Existing workflow regressions: 52 passed (26.437 seconds).
- Complete Python test suite: 720 passed (275.909 seconds).
- Only mail transport is mocked; password/code checks and model queries are real.
- All DB writes use temporary SQLite; no live mail, AI, S3 or production DB.

PostgreSQL row-lock/concurrent-request behavior is implemented but not established
by SQLite success. Run a two-connection PostgreSQL test before claiming concurrent
failure-limit or simultaneous code-consumption guarantees. Independent review,
real browsers, production configuration and full Q02 completion remain separate.

## Installation

`apply_dkss_q02_mfa_fix_20261027.py --repo <dkss-path> --apply` checks all targets
before writing, refuses unrelated local edits, preserves a backup, writes only
this auth change, its test file and this note, then runs the 68 Q02 tests.
It does not commit, push, check out a branch, run a migration or connect to a
production database. The user must review the test result before publication.
