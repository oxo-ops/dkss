# Shared-session follow-up after #399

Baseline main: d04503c3e2693c985b5d911d5097b3b1fb915a90, tree7dac0296c6bea5ecd723b25eda0cbdebb2d20497. Disabled TESTING-only candidate. This is not production authentication rollout or a duration-policy decision.

## Priority and scope from actual code

1. **Stale response safety:** `require_authority` already rejects revoked authority before routing, but HTML rejection formerly deleted the browser cookie. Apply the same server-only no-cookie flag to rejected documents, except explicit `/login`, which retains stale-cookie reset. Test B-login then delayed A-document rejection and an expired user's complete redirect/reset/relogin. This does not solve a request already authorized before replacement, late successful login, or final browser document content ordering. Do not claim all HTML races fixed.
2. **Small real write boundary:** `save_vehicle_analysis_feedback` directly commits operational status/comment changes. Reuse the independently reviewed `commit_vehicle_write` fence from evaluation. Preserve source-fingerprint freshness, per-company vehicle filters, validation, CSRF and duplicate-read behavior. Test real current-input acceptance and revocation immediately before fence, confirming no second row or cookie write. Synthetic fingerprints are built through the existing input service, not an always-true stub. Feedback itself alters inputs, so refresh the synthetic stored fingerprints before testing a second update.
3. **High-impact authorization changes:** `companies.itc_edit_company` changes company state; `auth.settings` / `verify_email_change` affect account settings; `masters` and invite service operations need role/target-specific transaction review. A vehicle-only fence cannot simply be copied to these. Existing auth/MFA lock order must stay compatible. No changes in this step.
4. **Vehicle lifecycle/batch writes:** `vehicle_master` has new/edit/toggle/bulk-delete/bulk-active and import-confirm commits. Define actor/tenant/target generation and batch atomicity before extension. External file/object effects and queued imports require separate treatment; DB locking cannot undo a transmitted side effect. No changes in this step.
5. **Full shared-device protocol and UX:** freeze old request owner/revision, reject mismatch without treating it as the successor, define explicit reauthentication reset, and decide device classification/unlock/expiry with real-device acceptance. Do not rely on a second SELECT alone or name selection as human identity proof. Push is a separate lane.

## Current acceptance and remaining limits

The candidate still refuses non-TESTING and production/remote configurations and has no default duration. Normal mode does not install its cookie interface and the commit helper keeps ordinary commit behavior. No migration, credential, production configuration or automatic deploy is introduced.

The HTML change only suppresses persistence for a request **already rejected** by the authority guard. It does not discard valid page state/flash updates globally, so existing normal workflows are not silently changed. `/login` is an explicit reset exception; its own late response ordering remains a known boundary. Shared-tablet authentication is not complete until those boundaries and physical-device tests pass.

User involvement is not required for synthetic code/CI work. Request a real tablet/browser sign-in and user-switch walkthrough only when the bounded UX is ready for device acceptance. Explain the exact step then; do not ask them to babysit tests, disclose a password in chat, or repeatedly approve the already-authorized non-production work.

## Verification notes

Initial session PG18 CI:26/26 passed14.688s at a5e822cf (run43699115030/job132766081250). Shared-Push expiry-loop test exposed an obsolete assumption: an expired logout response used to clear the cookie, then a single POST/login sufficed. The test now explicitly visits /login to reset, then authenticates in fresh request app contexts. This keeps runtime guards intact and avoids fixture g reuse. Focused local test passed1/1 in1.512s; updated-head PG/aggregate CI remains to be verified.
