# Shared-device history restoration candidate (not released)

## Scope and evidence
- Quality Word Library v15, pp60–61: section 33.3 and acceptance B require previous-user screens not to return from history.
- Source baseline: 885c81a3622f650fe8a7733e1fa478f274eb396a. Official main factory compared through GitHub fetch_file; source uses normal server authentication and already sends no-store for non-public responses (storage.add_security_headers).
- Existing base.js pageshow refreshes notification counts, not the entire authenticated document. This is a missing explicit UI revalidation boundary, not evidence of an actual information leak.
- Independent from durable session revocation (#403), MFA activation, shared Push ownership, password recovery and PostgreSQL acceptance. No DB or server-authentication changes.

## Candidate
For authenticated base-template documents, conceal and make the old document inert on pagehide. When restored with pageshow.persisted, keep it concealed and navigate with replace(current URL) to perform a GET under the current cookie. Do not delete or replace the cookie. Do not use reload() because a prior POST response could otherwise be resubmitted. No background polling, user-activity timestamp, token storage or new dependency.

## Verification
- `node tests/auth_history_js.cjs`: PASS, guest exclusion, initial normal display, pagehide conceal/inert, persisted restore navigation, direct persisted restoration.
- `git diff --check`: PASS.
- Chromium loopback synthetic fixture prepared in tests/auth_history_browser.cjs. Launch failed due to runtime socket Operation not permitted (also after approved escalation). This is NOT browser acceptance and not a failing feature assertion.

## Remaining before integration
- Independent review and exact-main rebase; parent may have newer changes.
- Actual Back/Forward restoration with logged-out or different-user cookie in Chrome, Edge, Safari and shared tablets; slow/offline restore; JS-disabled behavior.
- Headers cannot by themselves guarantee absence of BFCache. This guard is defense in depth, not a server authorization mechanism or OS-history erasure guarantee.
- Returning to a form now obtains a fresh GET; unsaved-form continuity must be tested. Do not claim safe draft restoration or full acceptance B.
- Pages not inheriting base.html are outside this limited candidate. No promise about exported files, OS snapshots, other open tabs or notifications already delivered.
- No merge, PR, deployment, production setting or Word replacement performed.

## Primary references checked 2026-11-16
- https://developer.chrome.com/docs/web-platform/bfcache-ccns
- https://web.dev/articles/bfcache

## Follow-up candidate and CI, 2026-11-16
- Rebased locally onto official main 07f07203.
- Explicit discard dialog protects restored unsaved inputs from silent loss; previous-user body remains inert and display:none (descendant visibility cannot undo ancestor display:none). No previous-user input is copied to storage or generic dialog.
- Actual Chromium history fixture added. Requires a real pageshow.persisted observation; includes same-user, logout, user switch, unsaved preservation until explicit discard. No artificial pageshow dispatch in the updated fixture.
- Dedicated GitHub CI uses disposable loopback personas, exact source, read-only repository permission, no application secrets or external sends.
- Git push was denied by automatic safety review for unverified private-code egress authorization. No workaround attempted; PR not created and CI NOT executed. Parent notified. Requires explicit authorization for publishing this candidate to oxo-ops/dkss quality/shared-auth-cache-20261116.
- This UI is still not accepted for production. Offline/error recovery and actual app template/session integration require browser validation. Returning users with drafts must explicitly discard rather than resume; that usability limitation may justify withholding integration until safe draft resume is available.

### Review corrections (local only)
- Replaced visibility:hidden with ancestor display:none!important, so descendant visibility cannot reveal old content.
- Added 8-second bounded HEAD reachability probe and generic visible retry outside inert body. Offline, timeout and server failure never unmask old content; next GET still independently authorizes.
- Node tests pass guest exclusion, normal lifecycle, conceal/inert, fresh navigation, explicit unsaved discard, offline rejection then retry. Browser fixture additionally tests actual offline restoration and recovery, but remains unexecuted because publication approval is blocked.
- No safe same-user draft resume implemented: the explicit discard choice is a limited fail-closed fallback, not the final desired usability. Recommend withholding production integration until actual browser checks and acceptance of this limitation or safe draft design.

### P2 initial-select correction
- Compare select options with the effective browser selection captured at script initialization, not defaultSelected attributes. A single select with no selected attribute is therefore clean when untouched.
- Six Node regressions pass: implicit initial selection, changed single selection, unchanged multiple selection, changed multiple selection, selection returned to baseline, dynamically added select conservatively protected.
- Pending Chromium fixture now includes a no-selected-attribute select on each authenticated document and explicit changed-select discard. Browser/CI still not executed; prior push rejection remains in force.
