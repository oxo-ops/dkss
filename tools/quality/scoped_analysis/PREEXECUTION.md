# Scoped pilot: integration and execution-readiness plan (NOT authorization)

## Source / integration

This independent local integration starts at main `da231b3` (#385/#386 included)
and merges #387 `c1d9f656f704e1f083d7714ec2872e9b22644efb` together with its
#382 ancestry. #387's base remains `quality/scoped-analysis-pilot-20261112`:
its CI is NOT evidence of compatibility with current main. No base retargeting,
main push, merge, deploy or production migration is performed by this plan.

## Before any real input or transmission

1. Independently review the integrated source, migration, normal callers, worker
   exclusion, persistent hold and count evidence design. Re-run full regression
   and isolated PostgreSQL concurrency/migration on that exact integrated head.
2. Record the target company, actual vehicle row ID and analysis state row ID
   from authorized read-only sources. A display label (e.g. HARUMICHI101) is not
   an ID. Confirm all peer/cohort records used by **ordinary** input collection
   are from the intended company. A single analyzed vehicle does not mean the
   provider sees only that vehicle. Include vehicles, repair/inspection records,
   driving evidence, company maintenance knowledge, source IDs and any free-text personal information in the
   disclosure inventory. Minimize through a reviewed input design, not by
   silently truncating the cohort and calling the result ordinary analysis.
3. Verify model/endpoint/settings at execution time. Render's absence of
   OPENAI_ANALYSIS_MODEL / OPENAI_MODEL plus code fallback supports a candidate
   gpt-6.1-sol model, not observed process runtime. Use the fixed Standard endpoint
   and explicit model; do not alter global worker settings to run the pilot.
4. Establish a maintenance window: drain/stop old executors, apply reviewed
   additive pilot_hold migration, update **all** job callers and verify new code
   and column before use. Old binaries do not honor the hold. These are future
   separately authorized operational steps, not commands to execute now.

## Preparing the complete count request (offline)

Use the ordinary `get_vehicle_karte_analysis_job_data(vehicle)` without a
`comparison_vehicle_ids` override. Reconcile the company/state/vehicle, and
normalize the payload exactly as ScopedJobBridge.load_input does. Bind its
`digest(detached)` to Target.input_revision. `prepare_count_material` calls the
same ordinary single-request builder, rejects multi-batch and acceptance-limited
input, explicitly sets service_tier=default, and serializes with the same JSON
settings as `_send`. It produces immutable generation bytes/hash plus count
bytes/hash. It performs no DB reads, writes, credential lookup or network call.

Count shape is POST https://api.openai.com/v1/responses/input_tokens with model,
instructions, input, text/schema and reasoning from the final generation body.
It omits output-only controls max_output_tokens/store/service_tier from the count
body, but the evidence still binds the **complete final generation hash** including
those controls. Do not estimate by character count or by records-only tokenization.

The raw bodies contain application data: keep only in access-controlled ephemeral
storage or memory for the approved operator, not logs, chat, PR artifacts or CI.
Do not fetch real production input merely to exercise this synthetic preparation.

## Authorization, count evidence and budget

Count is a separate disclosure to OpenAI, even if generation never follows.
Before the count request obtain authorization identifying provider, data scope,
company/vehicle and complete ordinary comparison inclusion. Verify current count
billing/limits from the provider; this plan does not assume counting is free.
If any fee is possible, include it explicitly in a separate approved count cap or
in the total cap; the generation ledger does NOT account for count charges.
Only then may a designated single owner send one count request, retain its
provider request ID/time/model/input_tokens and exact request hashes in protected
evidence, and stop on errors without automatic retry.

`bind_supplied_count` validates shape and both hashes and returns non-secret
metadata. It intentionally marks provenance_verified/authorization false: passing
a mock JSON response is not authenticated evidence, and the function grants no
permission. Independently authenticate provider provenance and record approval.
Then construct the Request and Policy for the exact counted bytes. Reconfirm if
source revision, model, prompt/schema, count, output cap or price changes.

The existing conditional profile reserves uncached input conservatively at
$2.50/million (including modeled 30-minute write) + output at $10/million.
At 76,000 input / 6,000 max output, generation reserve is $0.25, exactly. This
is an illustration, **not user approval**, not measured live tokens, and not an
all-inclusive price cap if counting/tax/other fees apply. Verify current prices,
USD and pricing tier; refuse counts >272,000 under this profile. Max output must
cover billed reasoning output too. Larger cost must not silently widen budget.

## One-shot execution and recovery (future authorized operation only)

Use a fixed durable single-owner ledger with explicit target, bytes, rates,
max_calls=1 and approved total generation cap. Never silently recreate a missing
ledger. The bridge commits its scoped permanent job hold before claim, validates
current ordinary payload revision, reserves before transmitting and uses one
verified-TLS request without redirects or retries. It has no auto invocation.
A process crash/uncertain reply retains the hold and reservation. Success also
retains hold. Do not clear hold based only on elapsed lease, status or new input.
Reconcile provider billing, ledger, saved result/source revision and worker state
before an explicit, separately reviewed release of the exact hold. Ordinary jobs
must remain blocked until then; missing evidence is a stop condition.

Accept normal saved-result/API/dashboard consistency separately from suggestion
quality. A clean demonstration vehicle may correctly produce no new proposals;
it does not prove a positive ranking or real paid run. Stop after the one target.

## Implemented count boundary (offline-tested; never invoked live here)

`CountPolicy` binds both immutable hashes, target/revision hash, explicit model,
operator approval reference, independently verified pricing evidence reference
and positive count-only reserve. References are audit identifiers, not proof of
consent; the operator must verify them. Count and generation have separate ledgers.
`CountLedger.create` is an explicit one-time local creation on validated POSIX
storage; reopening requires an existing same-identity file. It uses FULL sync and
IMMEDIATE transactions and reserves one call before transport construction. Every
outcome, including errors or a crash between reserve/send/save, blocks fresh owners.
Do not replace/delete it or create another path to retry an uncertain count.

`CountHTTPS.run` accepts an explicitly supplied credential and never reads secrets
from environment/browser/config. Fixed verified TLS, bounded response, fixed POST
endpoint and one attempt only; no redirects, proxy or retries. It stores only raw
response SHA-256, validated input_tokens, provider request ID and receive time,
bound to reserved complete generation/count hashes and target/model policy. Raw
response and authorization header are never logged or persisted. HTTP errors are
generic. A successful response is evidence received by this transport, not spending
approval or an independently authenticated operator attestation. Injected fake
transports used in tests are explicitly not provider evidence.

No generation Request/approval is minted automatically from count evidence. A
count-only reservation is not a provider invoice cap: verify current count price
and total approved spending before using the path. Reconcile count cost separately
from generation reservation. An invalid/missing provider request ID or result
shape leaves the attempt consumed rather than permitting a silent retry.
