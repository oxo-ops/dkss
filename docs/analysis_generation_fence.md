# Queued-generation save and failure fence

## Narrow scope

This fixes two reproduced cases where a newer input generation is already queued on the same analysis row while an older token-owning job finishes or fails. It does not change the 20-vehicle scan, one-job/60-second runtime, queue reservations, AI batching, retry policy for genuine same-generation failures, source proofs, scoring, schema, routes, or production configuration. The optional drain experiment is not included.

Before this fix, `finish` detected a different input hash but wrote the old bundle first, then replaced the newer deadline with finish + 2 minutes. `fail` unconditionally moved the state to error + 1 hour. Both could overwrite a newer generation's reservation. Reproductions use the actual job entrypoint, service, repository and reconciliation; only model transport is synthetic.

## Contract

- Capture the claimed input hash as a scalar before the claim commit. After loading input, separately capture the generated snapshot hash. Pass these explicitly to final success and failure, including failures before input construction returns.
- Read the latest row under `FOR UPDATE` after expiring cached ORM state, and require the original lease token. A replaced token is left entirely untouched.
- If the current queued hash matches neither the claim nor the generated snapshot, do not save the obsolete bundle or old exception. Preserve previous `result_json` bytes, `last_analyzed_at`, `last_error`, the new hash, reason and existing deadline. Release only this attempt's lease and retain pending work. A malformed/missing deadline alone receives a two-minute fallback.
- A generated snapshot may legitimately be newer than the claimed hash. If the queued row matches that generated snapshot, ordinary success/failure behavior remains valid. This is not incorrectly classified as supersession.
- Same-generation failures still retain the previous result and use the existing one-hour retry. No new attempt or spending limit is introduced.
- A rejected obsolete save returns False, as a rejected old-token save already does. The existing runtime failure count therefore includes this benign supersession; there is no new status enum or monitoring dashboard.

The fence only writes the analysis state. It does not alter source records or confirmation audit history. A real cancellation POST followed by real input loading/queueing immediately after real reconciliation is tested: previous bundle bytes and the newer reservation survive, audit/source bytes remain intact, and normal GET still suppresses the cancelled recommendation.

## Unqueued source changes are a different boundary

A separate immutable-V5 scratch witness commits a real cancellation POST **after** real reconciliation returns but before final save, without an intervening scan/queue. The vehicle epoch advances and cancellation audit commits, but the analysis input hash is unchanged. V5 saves the generated bundle as completed with no next reservation. Normal GET nevertheless reports `is_current=False` / `更新待ち` and suppresses the cancelled candidate. This witness does not demonstrate a wrong current cancellation score; it demonstrates stale persistence and replacement of the previously saved bundle. It is not fixed by this hash-only fence.

The older cancellation-during-generation test mutates/cancels **before** calling reconciliation, which can remove the candidate before save. The new witness is after that reconciliation. Do not treat these as the same interleaving or infer universal source-writer atomicity from either test.

When a later cyclic scan detects an unqueued source change, normal queue rules apply. Do not claim every unqueued source update is necessarily held for one hour: a newly detected hash can replace that retry. No universal epoch lock or new writer protocol is added here. Any further change should be justified by a concrete requirement impact, such as invalid history becoming a saved carry, rather than a blanket synchronization requirement.

## Isolated verification

- Eight new SQLite tests: real after-reconcile supersession, after-reconcile failure, load error before snapshot exists, newer generated snapshot success/failure, same-generation retry, replacement token, and a real confirmation cancellation plus real requeue through normal result GET.
- One updated existing SQLite regression asserts old bundle retention and exact newer deadline instead of obsolete-result success.
- Two new PostgreSQL cases are prepared for the existing owned official service. They cache the old ORM row, hold a competing queue transaction, observe a genuine `pg_stat_activity` lock wait, then commit the new generation. Both final save and failure must refresh the locked row and preserve the previous bundle/new deadline. Local execution deliberately skips this class; no local PostgreSQL is started.
- The official runner requires 27 non-skipped cases: the exact previous 16 runtime/concurrency/process cases, nine SQLite generation checks and two new PostgreSQL races. Re-running those 16 is relevant because final save/failure code changed; their prior pass remains evidence only for the immutable V5 head.

No real provider, production database, service/configuration update, dependency installation, or remote publication is performed by this candidate. Independent review and one guarded official run remain before publication/activation decisions.
