# Shared-device authentication: rollout gates and usable handover

## Product intent

Dedicated devices should not require an email code on every use. Shared tablets must distinguish the current operator without impersonation by name selection. Routine page changes must not trigger MFA. The existing password/MFA process remains intact until authenticator choices and recovery are reviewed. No timeout duration, trusted-device persistence, or MFA bypass is selected by this change.

## First usable increment: explicit handover screen

`/switch-user` is protected by the existing account/company access guard. GET displays the current operator and explains saving work; it does not log anyone out. Cancel returns to normal work. Confirmation POST has normal CSRF plus a random session-bound handover nonce. It calls the existing logout and returns to existing login, where the next operator supplies their own credentials and any enabled MFA. When submitted with the current browser cookie, a form left from a previous login cannot end that later login, including the same account signing in again. Requests carrying the old cookie and delayed GET/logout responses remain outside this guarantee. Invalid confirmation shows a neutral retry, not another person's selection list. No credentials are stored in browser local storage by this feature.

The nonce has no independent timeout policy; login/logout clears it with the session. Reopening the screen does not rotate it. All handover responses are no-store. This is not a full account-switch protocol and does not claim atomic completion for requests already executing.

The implementation is in a non-production branch only. The route is registered only with both TESTING and explicit USER_HANDOVER_PREVIEW; the default and production route maps do not expose it. The menu entry and real browser acceptance are pending coordination with the separate Push/base-template lane. Do not claim user-visible availability or deploy this branch merely because isolated tests pass.

## Code-backed remaining gates, in priority order

1. **Response ordering and server session ownership.** `session_authority.CandidateSessionInterface` suppresses rejected responses only. Successful HTML, login and explicit reset can still arrive late and overwrite state. Define stable server-side session handle plus owner revision; every request retains its original actor/revision rather than resolving to the successor. Bind CSRF and active requests to that revision. Test out-of-order successful login, repeated confirmation, Back/Forward, multiple tabs, network interruption and lock/unlock. The handover nonce does not solve this.
2. **Coverage of writes.** `commit_vehicle_write` fences only analysis feedback/evaluation, and only in TESTING. Inventory account/permission changes, master writes, vehicle edit/batch/import and external side effects. Each requires target-specific actor/tenant checks and lock order. Neither this UI nor existing global access checks prove in-flight write revocation.
3. **Authenticator and recovery UX.** Compare personal passkey/cross-device sign-in/security key with password plus additional factor as appropriate to actual tablets. Do not enroll all users under one shared device credential or shared PIN. Email sending success is not proof of safe account recovery. Preserve current MFA until replacement and fallback are approved.
4. **Session policy and activity.** Separate dedicated/shared devices, actual user activity versus polling, short absence versus handover, absolute/idle bounds and revocation. Choose durations only after real-device acceptance; no hidden defaults. A shared device must not inherit another person's trusted-device exemption.
5. **Production migration.** Candidate tables are outside normal models/migrations; runtime refuses production. Need reviewed schema migration, cleanup, multi-instance behavior, safe rollback preserving revocations, telemetry without tokens or personal bodies, and deployment plan. Do not remove TESTING restrictions before the gates above are closed.
6. **Operational acceptance.** Existing automated tests use synthetic data. Before rollout, request one concrete real-tablet walkthrough with two named test operators, enabled authenticator fallback, interruption/return and old-tab behavior. No password in chat, no repeated manual babysitting. Existing users must understand who is currently logged in, how to hand over, and what to do if authentication fails.

## Delivery separation

Code/test completion, merge, deployment, feature activation and real-device acceptance are separate statuses. No production configuration, automatic deploy, credentials, paid service or notification change is included. App delivery target remains FY2026; authentication gates apply equally to browser/PWA/native packaging.

## Branch verification

Focused synthetic checks: anonymous GET/POST blocked; confirmation/cancel and nonce stability; previous-login nonce rejection under current cookie; non-ASCII nonce rejected; candidate-disabled MFA still required; candidate-disabled valid CSRF confirmation; missing CSRF cannot end session; route absent with preview off or TESTING off. All eight checks passed in focused runs (six initial checks, one new valid-CSRF check, then changed CSRF rejection and new route-map checks). No live credentials, external delivery, PostgreSQL concurrency rerun, production activation, or real-browser UX acceptance in this increment. Independent review caught non-ASCII handling before publication; corrected with strict hex validation. Full integration CI is still pending.
