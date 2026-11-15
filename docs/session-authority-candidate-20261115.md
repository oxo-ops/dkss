# Isolated session authority integration candidate

Base: 0a0429f5794915a04e8bba1841628a49c2d9d9de. Not production-ready.

Original prototype could not be recovered through supported workspace, Library,
branch and task history reads. This is an explicitly authorized reconstruction,
not an assertion that the former prototype has been integrated.

## Implemented boundary
- TESTING-only and no Render/secure production-cookie enabling.
- SQLite in-memory only, or loopback PostgreSQL dkss_q02_ci with random
  q02_session_<32 hex> schema and bounded statement/lock timeouts.
- No implicit migration, no default expiry values, separate metadata.
- Actual password/MFA completion issues authority; pending MFA and logout revoke
  old authority. Protected API and protected file access consult server state.
- Traffic never moves deadlines. Cookie refresh cannot prolong server validity.

## Not implemented / do not ship
- Real activity renewal, lock/unlock, personal/shared device policy, auth epochs,
  concurrent login generation/CAS, idle-lock UX, Push detachment/ownership,
  account recovery, rollout/migration/backfill and deployment configuration.
- In-flight authorized requests may finish while another request revokes.
- Test client disables CSRF only in isolated test fixture; CSRF production code
  unchanged. No security weakening is proposed.

## Verification
New real-app SQLite integration: both MFA paths, logout copied-cookie replay,
background polling, idle and absolute expiry, protected files and legacy-cookie
fail-closed. Test-only isolation/metadata guards separately covered.
The new workflow is derived from existing Q02 PostgreSQL18 CI, same exact-head
checkout/credential restrictions and no SMTP/S3/VAPID/AI credentials. PostgreSQL
execution is not yet performed: this executor has neither PostgreSQL nor Docker.
`SESSION_AUTHORITY_REQUIRE_POSTGRES=1` forbids silent SQLite fallback.
Do not mark PG concurrency or shared-device end-to-end acceptance complete.

## Successor-claim follow-up (test-only)
A verified personal credential login replacing an existing authority now claims
that predecessor by atomic UPDATE (same identity, unrevoked, unexpired). Only one
request can begin replacement; a racing loser gets 409 and no new authority.
MFA-required replacement retires the prior person before the pending challenge;
MFA completion still requires the existing per-person challenge. Incorrect
credentials do not retire the current person. No name-only switch or shared PIN.

This does not identify a physical tablet or authenticate by device ownership.
Independent new-browser logins are not constrained by this predecessor CAS.
Concurrent response/cookie ordering can still force re-login, and user-switch
UX, authenticator choice, activity extension and physical presence are pending.
No production timeout, unlock method or MFA policy is selected here.

The dedicated PostgreSQL test uses two real Flask requests and independent
request sessions, aligning only the claim call with a barrier. SQLite skips this
specific concurrency case; the required PG job must execute it, not skip it.
