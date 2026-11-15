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
  complete device/session generation ordering, idle-lock UX, Push detachment/ownership,
  account recovery, rollout/migration/backfill and deployment configuration.
- In-flight authorized requests may finish while another request revokes.
- Test client disables CSRF only in isolated test fixture; CSRF production code
  unchanged. No security weakening is proposed.

## Verification
New real-app SQLite integration: both MFA paths, logout copied-cookie replay,
background polling, idle and absolute expiry, protected files and legacy-cookie
fail-closed. Test-only isolation/metadata guards separately covered.
The workflow derives from Q02 PostgreSQL18 CI, with exact-head checkout and no
SMTP/S3/VAPID/AI credentials. Dedicated PostgreSQL runs have now passed: 8 initial
integration/boundary cases, then 11 including real concurrent successor claims,
then 12 including delayed losing response and navigation-header handling. Each
result is tied to its recorded head/tree; it is not evidence for future edits.
`SESSION_AUTHORITY_REQUIRE_POSTGRES=1` forbids silent SQLite fallback.
Do not equate these narrow PG concurrency checks with shared-device end-to-end acceptance.

## Successor-claim follow-up (test-only)
A verified personal credential login replacing an existing authority now claims
that predecessor by atomic UPDATE (same identity, unrevoked, unexpired). Only one
request can begin replacement; a racing loser gets 409 and no new authority.
MFA-required replacement retires the prior person before the pending challenge;
MFA completion still requires the existing per-person challenge. Incorrect
credentials do not retire the current person. No name-only switch or shared PIN.

This does not identify a physical tablet or authenticate by device ownership.
Independent new-browser logins are not constrained by this predecessor CAS.
Non-transition request response/cookie ordering still requires review; user-switch
UX, authenticator choice, activity extension and physical presence are pending.
No production timeout, unlock method or MFA policy is selected here.

The dedicated PostgreSQL test uses two real Flask requests and independent
request sessions, aligning only the claim call with a barrier. SQLite skips this
specific concurrency case; the required PG job must execute it, not skip it.

## Late losing transition response
A failed CAS response now renders a neutral 409 page, clears only request-local
identity for rendering, and suppresses Flask session cookie persistence. It does
not redirect automatically or delete a cookie. The user can open the current
session explicitly to confirm who is logged in. This avoids the losing response
replacing the winning tab's cookie. No names/passwords are reflected in this page.
The response is no-store. CSRF and MFA behavior are unchanged.

Only the conflict marker generated inside the authenticated replacement handler
can suppress persistence. The test-only interface refuses to replace a custom
session interface. Other in-flight request ordering and a full shared-device
switch UX remain outside this narrow acceptance claim.

## CSRF-on acceptance follow-up
The earlier candidate fixture disabled CSRF to isolate authority behavior. New
cases enable the real CSRF extension: missing token cannot issue authority;
a previous person's form cannot log out the succeeding person; MFA transition
requires a fresh CSRF form token and the existing valid challenge. Every request
gets a fresh app context so fixture-level g caching does not fake real behavior.
No CSRF production implementation or bypass was added.

## Remaining scope in priority order
1. General in-flight/stale-response ordering beyond CAS losers: expired API,
   ordinary page response, logout and failed-CSRF response must not overwrite a
   newer person's browser cookie. Do not claim solved by the 409-specific guard.
2. Authorization at sensitive write commit boundaries and account-wide revocation
   evidence; existing user identity/password/lock checks remain mandatory.
3. Shared-device Push: default off until ownership/detachment and queued payload
   privacy are accepted. Coordinate with the Push lane before editing.
4. Explicit person-confirming switch/lock UX and activity-renewal classification.
   No name-only selection or shared PIN. Polling, focus and client time alone
   must not renew authority. Production duration/unlock method still undecided.
5. Authenticator recovery, device management, rollout/migration and actual
   tablet/browser validation. A physical device is not proven by a cookie.

Next implementation should remain isolated: general stale-response handling
requires a browser family/generation design and real response-order tests, not
an unconditional session.clear or retry. Changes must preserve CSRF and MFA.
