# Connected normal-screen acceptance

This is the connected acceptance for the fixed video scope, not a new product
feature. The fixed eight video scenes and completion boundaries are recorded in
[the integration scope](../../docs/features/video-normal-flow-acceptance-20261111.md).
The three optional-confirmation conditions alone do not complete the video scope.
Reuse the existing per-feature results and run the final candidate's
browser/full regression together. Do not retry Chromium in a host already known
to lack the required OS support.

## What the Flask tests actually do

`tests/test_video_connected_flows.py` borrows fixture helpers, not their collected
test cases, and exercises normal Flask routes on a new temporary SQLite DB.

1. `test_inspection_notification_human_stop_and_recheck_keep_one_vehicle`:
   create the normal daily checklist with GET, POST each answer with `save-one`,
   POST `complete`, repeat `complete` (409 and no new notification), read the
   admin notification, try the same notification/vehicle as company B (404),
   POST the human `operation-judgment` as unavailable, read the computed high/60
   on normal analysis and dashboard, POST defect `repair`, reject old analysis
   `feedback` (409), POST a recheck, and POST the new human operation decision.
   The inspection, notification, maintenance and defect link retain their IDs.
2. `test_normal_50_keeps_shared_order_with_dashboard_safety_and_comparison_panels`:
   the same normal inspection submission and a human available decision produce
   medium/50. Three proposals (computed + saved high/low) preserve ID, revision,
   label, points and order between normal API and dashboard. Overview and analysis
   point at the same normal result endpoint. The dashboard safety section and
   analysis comparison/replacement panels remain present.
3. `test_registered_recheck_waiting_25_is_not_an_automatic_operation_decision`:
   POST human available, POST repair/recheck-waiting, and read medium/25 with all
   three axes unknown. The text says this is a registered state, not proof that
   an actual check did not happen. Recheck does not itself authorize operation.
4. `test_completed_manual_work_receives_invoice_without_second_completion`:
   POST normal manual maintenance completion, POST a PDF to `data-import/jobs`,
   run the real queue worker with synthetic extraction, GET matching candidates,
   POST confirmation using the actual signed candidate token. The same existing
   maintenance ID reaches cost/history/parts/plan actuals/analysis and source PDF,
   with no second completion action. Re-upload of the same PDF returns 409.
5. `test_invoice_confirm_correct_resend_and_late_cost_stay_one_actual`:
   POST upload, real queue worker, POST confirmation, read all connected screens
   and actuals, replay confirmation/re-upload (409), POST a read correction,
   upload another document, explicitly choose the same maintenance, POST the
   additional-cost review and reject its replay. One maintenance and one part
   remain. The actual links both preserved originals. Pre-existing periodic and
   vehicle-inspection plans remain planned and no execution is created.

### Synthetic/stub boundaries

- Companies, accounts, vehicles, office/driver assignment and one safety item are
  synthetic. Sessions are fixture-authenticated; CSRF/rate limiting are disabled.
- Inspection answers, human judgments, maintenance, recheck events, notifications,
  invoice drafts/confirmation, financial review and source/part links are written
  by the real normal routes/services.
- Saved AI recommendation wording is synthetic. Input gathering, server-issued
  priority references, source evidence, validation, freshness cache/projection,
  score computation, feedback stale checks, cost readers and analysis inputs are
  real and are not frozen or stubbed.
- Classification and OCR are replaced with deterministic synthetic PDF content.
  External AI, SMTP, push, S3 and network services are not exercised. No result is
  evidence of real OCR accuracy, delivery, production data, PostgreSQL concurrency
  or professional acceptance of the trial priority policy.
- Dashboard can add a conservative freshness caveat. Identity, order, scores,
  axes and source attribution match the normal result API; caveat wording is not
  asserted byte-for-byte equal.

## Isolated Flask execution

Use a Python 3.12 environment checked against every pin in `requirements.txt`.
The wrapper uses `env -i`, a disposable HOME/TMPDIR, disabled integrations, and the
existing audit guard which rejects Python network connects and SQLite connections
outside the new temporary root.

```sh
bash tests/video_connected_browser/run-isolated-tests.sh "$PWD" /absolute/venv/bin/python
# A later edit can be tested only in its affected class or method:
bash tests/video_connected_browser/run-isolated-tests.sh "$PWD" /absolute/venv/bin/python \
  test_video_connected_flows.ConnectedInspectionFlowTests
```

## Exact-candidate browser harness

`acceptance.py` requires a clean worktree and exact expected SHA. It prepares each
original scenario with the real fixture POSTs above, then bridges the browser to
Flask in-process using **same-origin GET-only** Playwright routes. Only the new
`confirmation_*` cases below permit two exact confirmation-form POST routes. It never launches a
live Flask server. Python network access and all external browser requests are
denied. The original six cases still abort all browser writes and cover rendered
GET navigation, not typing/submitting their forms; their POST behavior is covered
by the Flask tests. This distinction is unchanged by the new confirmation cases.

Run only after the candidate is fixed, in the official CI/browser environment:

```sh
for scenario in normal instruction recheck invoice periodic_instruction periodic_timing; do
  DKSS_BROWSER_ARTIFACT_DIR="/absolute/artifacts/$scenario" \
  bash tests/video_connected_browser/run-isolated.sh "$PWD" /absolute/venv/bin/python \
    --expected-sha "$EXPECTED_HEAD" --case "$scenario" \
    --run-browser --chromium /absolute/authorized/chromium
done
```

Use `--preflight-only` without `--chromium` to verify fixture/GET preparation for
the original cases, or the explicitly described HTTP sequence for the new cases.
It writes `PREFLIGHT_PASS_BROWSER_NOT_RUN`, never a browser pass. Browser cases
check 1440/390/320px, priority order and points, dashboard safety coexistence,
comparison/part coexistence, drawer Close/Escape and history navigation, or the
invoice history/cost/parts/analysis sequence. JSON results include exact SHA/tree,
browser version, blocked/failed requests and script errors, plus screenshots.
Business-table snapshots must remain unchanged after GETs; usage/last-selected
vehicle/periodic-notice bookkeeping is excluded explicitly.

The harness was prepared without starting local Chromium. Add its six scenario
invocations to the final integrated CI job; do not create repeated full runs for
small changes. Full regression and exact-candidate browser results are separate
from passing focused Flask tests.


### Browser boundary, specifically

The browser follows the displayed notification's link to the original daily
inspection, and the displayed history link to the same maintenance detail and
its original-PDF download (SHA-256 compared with the preserved source). It also
clicks the overview proposal link into analysis/details. The notice is already
marked read using its real Flask target route before the protected browser
baseline, so the browser does not exercise the unread-notice auto-mark POST.

The browser **does not** type/submit daily-inspection answers, completion,
human operation judgments, repair/recheck forms, invoice upload/confirmation,
cost correction/review, or proposal feedback. Those POST sequences are tested
through the real Flask client with synthetic authenticated sessions and CSRF
disabled. Passing this harness means rendered results and the specified real
links work; it must not be described as all operations completed in a browser.
Browser screenshots/acceptance remain unverified until official CI runs them.

## Additional K61/K63 invoice-to-analysis acceptance

`test_corrected_late_invoice_reaches_rendered_comparison_and_generation_transport`
is a focused sixth Flask case, added after the connected checkpoint. It creates
one invoice-backed maintenance through upload/worker/confirmation, corrects the
amount, and explicitly attaches/reviews a later invoice. It reads the normal
analysis route after each relevant state, without stubbing comparison, cache,
summary, source gathering or priority projection.

The assertions compare both real template context and rendered HTML with records:

- Own maintenance cost: 163,900 -> 160,000 -> 163,000 yen. Pending later costs do
  not count before review. Distance 1,000 km gives 163.90 -> 160.00 -> 163.00 yen/km.
- One part remains attached to the same work, with the confirmed replacement
  date and 10,000 km at replacement. The next day's registered 10,250 km yields
  250 km since replacement, visibly shown in the part row.
- Minimal same-company/model/year peers produce a cohort of three and two
  calculable samples. Known 0 and 10 yen/km average to 5.00, not a pooled 8.00;
  the third peer's absent data is excluded rather than treated as zero.
- The analysis URL is registered GET-only, so there is no invented manual POST
  generation path. The real scheduled queue/job, real input serialization,
  generator validation and saved-result service run. Only urllib `urlopen` is
  replaced with a deterministic response. The wire input contains the corrected
  163,000 yen and part evidence tied to the original document's SHA-256. The job
  saves the actual source snapshot/fingerprints; normal result GET reports it
  current and returns the same saved source evidence.

The fake model response deliberately has **no recommendations**. This proves
input/transport/validation/persistence wiring, not model advice quality or a
priority score inferred from an invoice. Session/CSRF/OCR boundaries above still
apply. The existing browser invoice scenario is unchanged; these additional
numeric/transport assertions are Flask/HTML acceptance, not browser-rendered
acceptance or a claim of completing form submissions in a browser.


## Notification-related priority browser extension

The existing `instruction` and `recheck` scenarios also use the **checker-owned
notifications created by the real operation/repair routes**. Preflight checks
exact proposal ID, revision and event binding with high/60 or medium/25, plus
access to the same inspection source. The original admin approval notice is an
unsupported representative and must have no related-priority summary.

At each configured browser width, the checker opens the actual notification row,
reads its list summary and detail, clicks its proposal link, verifies the same
proposal fragment/title/score in the analysis drawer, and follows the drawer's
original-record link to the same inspection. This does not recreate notifications
or alter their text, event, human decision or ordering. Both specific synthetic
notices are marked read through their ordinary Flask target GET before the
protected snapshot. Browser POST remains blocked; unread auto-read behavior and
browser form submission remain outside this harness. Previously covered foreign
company/owner/revoked-identity/old-event boundaries are not repeated here.


## Periodic shared-priority browser extension

`periodic_instruction` and `periodic_timing` prepare an actual periodic record,
normal proposal POST, real worker save and normal result GET using the dedicated
periodic fixtures. Only AI recommendation wording is synthetic. The registered
human stop instruction produces high/60; the adopted manufacturer timing rule
produces medium/35. Preflight verifies the same shared assessment and one-proposal
label counts. It does not replace missing inputs with zero or backfill old jobs.

At 1440/390/320px the browser reads the normal follow-up page, verifies its card,
score and count, opens/closes the common source details, and follows the actual
inspection-list link then browser Back. Human instruction attribution or the
adopted reference/quote must be visible as appropriate. External reference links
are checked as attributes only, never visited. The completed fixture avoids any
auto-generation POST; writes remain blocked and saved business rows unchanged.
This extends rendered-read acceptance, not browser form/AI-generation acceptance.
The existing CI job reuses the same pinned browser and also runs the four Node
periodic presentation contracts. No second browser environment is introduced.


## Optional source-confirmation forms: narrowly permitted browser POSTs

`confirmation_acceptance.py` is dispatched only for `confirmation_manufacturer`,
`confirmation_legal`, and `confirmation_progression`. The original six scenarios
and their GET-only bridge are unchanged. The new scenarios use the same isolated
wrapper, pinned browser, clean expected SHA, and artifact format. Invoke each:

```sh
for scenario in confirmation_manufacturer confirmation_legal confirmation_progression; do
  DKSS_BROWSER_ARTIFACT_DIR="/absolute/artifacts/$scenario" \
  bash tests/video_connected_browser/run-isolated.sh "$PWD" /absolute/venv/bin/python \
    --expected-sha "$EXPECTED_HEAD" --case "$scenario" \
    --run-browser --chromium /absolute/authorized/chromium
done
```

For these three scenarios only, same-origin JSON POST is permitted to exactly
`/vehicle/karte/<fixture_vehicle_id>/priority-confirmations/preview` and
`/vehicle/karte/<fixture_vehicle_id>/priority-confirmations`, with no query string.
Other writes, other vehicles' POSTs and external requests are rejected. There is
no live Flask server or access to a production or existing database. Browser requests forward the
actual rendered CSRF token to Flask; CSRF is enabled after fixture seeding. Fixture
authentication is synthetic and rate limiting is disabled. A missing-CSRF request
is rejected in HTTP preflight. Source providers, parsers, authorization checks,
calculators, priority projection and the normal queue/job are real. Only the model
urllib transport is replaced with an empty recommendation response, as described
below. No external AI/OCR request is made and no result JSON is directly seeded.

Sources are entirely fictional but read by real providers:

- Manufacturer: `ManufacturerConfirmationWorkflowTests`, the nonperiodic
  instruction-only original PDF. Select the current observation, actual rule,
  condition quote and action quote from the normal API's options.
- Legal: `CertificateSourceTests`, a synthetic Japanese PDF with vehicle identity
  and a **previous-day expiry**, parsed from original bytes. This avoids depending
  on interpretation of the expiry day itself. The public MLIT reference is
  checked as a link attribute, never visited; the fixture is not a real legal
  determination or a statement about actual extension eligibility.
- Progression: `ProgressionWorkflowTests.prepare_pair(same_day=True)`, ordinary
  HTTP inspection/repair/recheck/detail/completion/human-decision records. The
  synthetic prior observation is resolved at 10:30 and a distinct later observed
  comment is registered at 12:00. Only the fixture clock is controlled. Exact
  current/baseline/relation option values are selected, not inferred by label.
  Five additional distinct historical observations and confirmations are created
  through ordinary routes before the protected baseline. With the selected form
  confirmation this gives six source-bound candidates for the existing overview
  limit of five, not six copies of a seeded model proposal.

`--preflight-only` exercises real options, preview and original-source GET, CSRF
rejection, required-statement rejection, confirmation, replay 409, atomic
correction (withdrawal plus new confirmation), stale-preview 409, cancellation,
cancel-replay 409 and a fresh confirmation after cancellation. After correction
it drives the real queue/job with an empty model response, checks current normal
result GET with manufacturer/60, legal/60 or progression/65, and after cancellation
checks immediate normal GET and a second normal generation. The progression case
must go from six candidates to five, preserving the other five proposal IDs. It
checks static non-nesting of the two forms. This is HTTP preflight, not a browser
result.

The prepared browser sequence runs at 1440/1024/768/390/320 pixels. It uses actual
selects, original text/link previews, fixed required checkboxes and submit
buttons. An unchecked statement must stop submission in the browser. A real
double-click must produce one save, and a deliberate fetch replay of its captured
synthetic body must return 409. Another browser tab holds an old preview while
the first tab corrects the confirmation; the old tab's actual submit must fail
with 409. Cancellation is first dismissed, then confirmed, and replayed (409).
History must show withdrawal of the selected confirmation after cancellation;
the five unrelated progression confirmations must remain active.
Escape closes/focuses the optional details, and the ordinary overview link and
Back remain usable without requiring confirmation. Forms must be separate, not
nested in each other or the existing normal form, with no page overflow.

After **every** bridged request, all business tables and existing audit rows are
compared with the protected baseline, including original PDF bytes, source
records, inspection answers, repairs, operation judgments, notifications, users
and saved AI JSON. Only this company and vehicle's `analysis_input_epoch` bucket
and `analysis_input_read_cache` row are exempt as bookkeeping. During the explicit
background-generation helper only, its single normal `VehicleKarteAnalysis` row
may change through the actual queue/job. Other companies' and vehicles' analysis
rows remain protected. The target saved result is re-protected immediately after
the job, so browser GET/confirmation POST cannot edit its saved JSON. Only a successful confirmation-save request may append
new `ChecklistEvent` rows, scoped to this company/vehicle and the confirmation or
withdrawal event types; every previously appended row remains immutable too.
Correction must append two rows, cancellation one, and rejected requests none.
No raw signed token is written to the result artifact.

These are preparation assertions until the official browser run returns PASS.
The new form acceptance does not convert the older inspection/invoice flows into
full browser form coverage, establish real AI/OCR quality, or reconstruct driver
or office transfer history from current vehicle attributes. Existing history
coverage proves arrival at the original linked record. Full video completion
requires all fixed scenes and the final integrated checks, not these three forms
alone.


### Form confirmation to normal generated candidates

The first form cycle in each new scenario continues after its correction save:

1. The fixture helper calls normal `get_vehicle_karte_analysis_job_data`,
   `queue_vehicle_karte_analysis`, and `run_vehicle_karte_analysis_job`. Only the
   synthetic job due time is advanced. The normal input builder, candidate
   completion, source validation, pre-save reconciliation and persistence run.
   `urllib.request.urlopen` returns `recommendations=[]`; no result object or
   rendering function receives directly seeded proposals.
2. The browser reloads ordinary pages and obtains the usual result GET. At all
   five widths it checks manufacturer high/60, expired-certificate high/60 or
   recurrence high/65, shared order, overview counts, analysis rows and source
   details. Progression checks exactly five overview cards plus the actual
   `残り1件を分析で確認` link, arriving at all six analysis candidates. It opens the
   selected proposal's ordinary detail control, reads its confirmation actor,
   fixed statements and original text, then follows an internal original link.
   PDF responses are compared by SHA-256 against the source response. This proves
   the rendered link reaches original bytes, not visual PDF-viewer text quality.
   External MLIT links remain attributes only.
3. The selected confirmation is cancelled through the browser form. The fixture's
   normal HTTP result GET must immediately omit only its proposal without changing
   saved result JSON. A second normal queue/job then saves the cancellation-
   consistent result. Browser overview/analysis GETs at all widths must omit the
   selected proposal and retain the same five unrelated progression IDs.

The generation is controlled fixture background work, not a new user-facing
button or a third permitted browser POST. Ordinary reload is used instead of
waiting through the product's 60-second poll at every width; the product timer
and rendering code are unchanged. Only one confirmed-state job and one cancelled-
state job run per scenario. The remaining form-width cycles do not trigger extra
model generations. Result artifacts record transport call counts, normal analysis
state ID, result digest and saved candidate count, without raw signed tokens.
These assertions test deterministic inclusion from verified synthetic evidence
despite empty AI advice, not the quality of real model advice.

### Verification status of the recovered extension

The extension was reconstructed from previously sent edits after environment
loss. Its final exact-candidate preflight and browser acceptance remain pending.
The last legal/progression HTTP rerun has no recovered outcome and is not a pass.
No browser run has been completed for this extension. Earlier component tests
are not evidence that the reconstructed candidate passed. Use the final clean
candidate's official CI artifacts to establish browser/full-regression results.
