# Synthetic native bridge integration

Candidate only. No operational scheduler, sender, production state, credential,
external notification, merge or deployment is enabled.

native_ledger_bridge.js runs with the native projector while raw replies are
transient. It emits a pseudonymous resource alias and hashed provider IDs, fixed
marker names/enums and timestamp-shaped values only. Unknown or ambiguous failure
markers remain reviewable through fixed sentinels; invalid routing/identity rows
remain rejected. Native/runtime code loading must use trusted repository code.

The sanitized query/reply pages then enter the original Python log_ledger.observe
without modifying that ledger. The provider ID is hashed a second time by the
original ledger. Thus this format MUST NOT be mixed with original-resource state,
and changing the alias convention is a migration, not a reset. The example is
synthetic only; it is not a completed live monitoring pipeline.

bridge_store_trial.py requires an existing valid ledger and builds one versioned
payload. commit_once uses the store's expected version once. Conflicts and unknown
outcomes propagate; no retry, state reset, delivery or acknowledgment is inferred.

Verification: nine focused Python bridge/store tests passed, alongside nine native
projection tests. Cases include linked two-page duplicate receipt, replay, two
writers holding the same version (model), conflict, injected unknown-before/after
write, missing/corrupt state and preservation of unknown/mixed failure markers.
Independent static review identified missing-state reset and dropped review
markers; both were corrected with affected tests. These are not simultaneous
service-writer or crash-durability guarantees.

A synthetic integrated two-page bundle was saved to the same dedicated Library
probe with expected version 1, producing version 2. Readback JSON exactly matched:
one unique record, one duplicate suppressed, read_checkpoint null, no send.
Prior probe verified a stale version conflict. No real logs or original provider
identifiers were put in Library or GitHub. Probe identities remain private.

ACL visibility is NOT verified: available read/list metadata does not expose
owner/public-link/inherited access lists. No sharing change was made. Do not admit
real operational data or activate monitoring until the selected private store's
access can be verified. Unknown write outcome requires fixed-ID readback and
reconciliation; it never permits a blind retry or another notification attempt.
