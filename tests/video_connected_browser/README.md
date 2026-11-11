# Connected normal-screen acceptance

This is the connected acceptance for the fixed video scope, not a new product
feature. Reuse the existing per-feature results and run the final candidate's
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
scenario with the real fixture POSTs above, then bridges the browser to Flask
in-process using **same-origin GET-only** Playwright routes. It never launches a
live Flask server. Python network access is denied and browser writes/external
requests are aborted. This covers rendered GET navigation, not typing/submitting
forms in a real browser; POST behavior is covered by the Flask tests.

Run only after the candidate is fixed, in the official CI/browser environment:

```sh
for scenario in normal instruction recheck invoice; do
  DKSS_BROWSER_ARTIFACT_DIR="/absolute/artifacts/$scenario" \
  bash tests/video_connected_browser/run-isolated.sh "$PWD" /absolute/venv/bin/python \
    --expected-sha "$EXPECTED_HEAD" --case "$scenario" \
    --run-browser --chromium /absolute/authorized/chromium
done
```

Use `--preflight-only` without `--chromium` to verify fixture/GET preparation only.
It writes `PREFLIGHT_PASS_BROWSER_NOT_RUN`, never a browser pass. Browser cases
check 1440/390/320px, priority order and points, dashboard safety coexistence,
comparison/part coexistence, drawer Close/Escape and history navigation, or the
invoice history/cost/parts/analysis sequence. JSON results include exact SHA/tree,
browser version, blocked/failed requests and script errors, plus screenshots.
Business-table snapshots must remain unchanged after GETs; usage/last-selected
vehicle/periodic-notice bookkeeping is excluded explicitly.

The harness was prepared without starting local Chromium. Add its four scenario
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
