# PR377 remaining supplemental validation

This disposable validation branch checks only the remaining 3 HTTP preflights and 13 common-priority browser scenarios. It never modifies the application checkout, product branch or main. It is not a replacement for original PR CI, full regression, production validation or merge approval.

## Two separate identities

- Application: `30d4dfeee97f69bd00650c6bf56a5ce234f34437`.
- Application tree: `31bb88b2d7a1a93f4c52f5aeefd59e97a8c8d3ea`.
- Requirements blob: `f29b6951157ecb12ef81490f42dfb5d57bdd9330`, 38 exact pins.
- Previous validation commit: `05d5e5f21efb9f3f3bba4be49a1a137efb545c10`.
- Previous validation tree: `71ee550834e472cbc18679e96e2ffaadc708b582`.
- This validation commit is the triggering `github.sha`; its exact commit, tree and four file hashes are recorded at runtime.

The workflow checks out the frozen application into `application/` and this validation commit into `validation/`, with separate read-only checkouts and no persisted credentials. It verifies the application commit, tree and clean status and all required harness/guard blobs before execution, between cases and after execution. The validation checkout must also be clean, match the triggering SHA and contain exactly the four files listed below.

## Observed fixture defect and minimal correction

The previous supplemental run stopped in the manufacturer companion-certificate preview before the browser scenarios. An isolated reproduction against the unchanged application observed HTTP 400, `ok: false`, and `選択原本の同一車両・満了日を照合できません`. The real certificate reader returned `explicit_test_or_nonofficial_original` and `literal_verified: false`. The manufacturer's synthetic vehicle model `FICTIONAL-ONLY` had been embedded into the synthesized certificate; that literal is deliberately rejected by the existing nonofficial-original guard.

The validation-only copy of `confirmation_acceptance.py` adds exactly two executable lines at the start of the manufacturer branch, before either source is prepared:

```python
c.vehicle.model_code = 'TESTMODEL'
c.db.session.commit()
```

Two comments explain why. `TESTMODEL` is the existing certificate fixture's synthetic model. The product reader, rejection guard, vehicle identity checks, source checksums, source creation, real preview/save routes, CSRF, queue/job execution, score computation and all original assertions remain unchanged. No proposal/result/score is newly seeded and no source reader is mocked. Existing explicitly documented fixture operations, including the one-field source revision/restore and one-key saved-source omission, are unchanged.

The diagnostic reproduction used Python 3.12.14 and verified all 38 application pins without changing its existing environment. After the fixture-only change it observed preview HTTP 200, `ok: true`, `literal_same_page_matched`, and the complete manufacturer HTTP preflight passed. The manufacturer reader still found its unrestricted original instruction and returned preview 200. The real normal job retained 2, then 2, then 1 candidates across generation, historical carry and cancellation; the independently confirmed legal candidate remained present. The unchanged certificate-source and manufacturer-workflow suites also passed 34 tests, including the explicit-fictional-original negative case. This is HTTP-only diagnostic evidence, not a browser pass or a claim of the official container's Python 3.12.3 execution.

Frozen application helper Git blob: `77038626212de6c5b1c569ad420274e97a16cfc8`.

Corrected validation-only helper Git blob: `f3df79a596a9ad2e7f9bb3dd719f659c5187abce`.

Corrected helper SHA-256: `f47206343983bcf896dbd875995e9401a5c794e113c0cf463be9c570a54fb7a9`.

## Separate harness, unchanged isolation

The preparation script creates a new directory outside both checkouts. It copies only these three frozen files into their original relative layout and verifies byte equality and Git blob hashes:

- `tests/video_connected_browser/acceptance.py`: `97f6b6707d88c278cadd975b858762d112f37d56`.
- `tests/video_connected_browser/run-isolated.sh`: `f1be008f4e441e09b8f22ff41772d114fb0ba38d`.
- `tests/history_presentation_browser/guard/sitecustomize.py`: `fecc07a6a8d0ddbbe19cc2cbd4d234dc209e7cef`.

Only the corrected helper comes from the validation checkout. Its reviewed Git blob is enforced. The copied acceptance entry point still receives `--repo application/` and the frozen expected application SHA, so all application and fixture imports remain from the frozen source. The helper is resolved from the external script directory; potential earlier-path shadow modules are rejected. The runtime provenance manifest records both identities, original and corrected helper hashes, every required frozen harness hash and the executed helper path. Copies are rechecked between cases and at aggregation.

The original `env -i` wrapper and `sitecustomize.py` are not edited. They retain the disposable HOME/TMPDIR, disabled integration settings, Python network-connect block and SQLite-outside-fixture-root rejection. Common, stage2 and the six nonconfirmation connected scenarios execute directly from their original application paths. Only the three confirmation scenarios use the external helper copy. Browser requests still use the original in-process Flask bridge, not a live listener or production service.

## Execution and honest aggregation

Every case is an independent subprocess with a fresh original isolation wrapper:

- 3 HTTP-only: manufacturer, legal and progression confirmation.
- 13 browser: common; stage2 instruction/recheck/timing; connected normal/instruction/recheck/invoice/periodic_instruction/periodic_timing/manufacturer confirmation/legal confirmation/progression confirmation.

A scenario failure or launch failure does not skip the remaining independent scenarios. Each case has an execution log, status, exact process exit code and its original report JSON. Source or harness-integrity failures stop further execution. Interrupted, missing or never-started cases remain incomplete, never passed.

The aggregate step runs even after an ordinary scenario failure. It requires all 16 unique expected execution entries with zero exits, all 16 corresponding reports, exact source identity, synthetic-only/no-production flags, and the original browser/preflight status fields. Browser passes also require `browser_started` and `browser_acceptance_passed` to be true. HTTP-only passes require both to be false. Missing reports, wrong scenarios, nonzero exits, skipped cases or dirty source fail the aggregate. It always writes `remaining-summary.json` when aggregation is reached. A cancellation or infrastructure failure before aggregation cannot yield a passing workflow.

The artifact contains original scenario JSON/screenshots/logs, `scenario-exits.json`, `harness-provenance.json`, source identity and exact runtime/install records. Its name is `pr377-remaining-container-30d4dfe-RUN-ATTEMPT`, with 14-day retention. Do not mix these results with orchestration self-tests or the previous run.

## Runtime preserved

The official Microsoft image and installation procedure are unchanged:

- Image: `mcr.microsoft.com/playwright/python@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d`.
- Official tag: `v1.62.0-noble`; listed amd64 digest `sha256:51d31fdfacb0cff99a1a724152e34ae408d2bd4e7da310ff157450f49261cc59`.
- [Official registry](https://mcr.microsoft.com/en-us/artifact/mar/playwright/python/tag/v1.62.0-noble), [versioned Dockerfile](https://github.com/microsoft/playwright-python/blob/v1.62.0/utils/docker/Dockerfile.noble), [vendor documentation](https://playwright.dev/python/docs/docker).
- Playwright Python `1.62.0`, Node `24.22.2`, application requirements exactly verified at runtime.
- Official container's previous run recorded Python `3.12.3`; this run records the exact version again. Original PR CI used Python `3.12.16` on ubuntu-26.04, so runtime equivalence is not claimed.
- Existing image-provided virtualenv creates a new environment; ordinary isolated pip installs from official PyPI. No apt, install-deps, playwright install, new dependency, DNS/proxy change or custom package mirror.
- Default GitHub container security remains unchanged. No privileged/capability/seccomp/network/IPC flags, `safe.directory` exception, ownership workaround or new browser flags.

## Earlier evidence is preserved, not rerun

[Previous supplemental run 43043343085](https://github.com/oxo-ops/dkss/actions/runs/43043343085), [job 130600661947](https://github.com/oxo-ops/dkss/actions/runs/43043343085/job/130600661947), used the same frozen application and the previous validation commit above. The overall run failed on the companion fixture, but its independent Node 41 tests, comparison 14 cases and dashboard 6 widths passed. Those groups are not rerun by this workflow and are not counted as current-run passes.

Original evidence remains at:

- Common/runtime/failure artifact `13866322166`; digest `sha256:f74d618aaa2bc11cde34e7643d4105bd9d0d8a25c2e92f84a4b54a9215c4f4fd`.
- Comparison artifact `13865109256`; digest `sha256:a661361e19fa74cb9986d68897ce51b0fd6aa4c9d040f1e847954b0a63d519c9`.
- Dashboard artifact `13865104317`; digest `sha256:5f09548863045092d702db807df6a1b01046c62d0042a41549d9ab11147670a2`.

GitHub listed these artifacts on 2026-11-11 UTC as unexpired, with expiry 2026-11-25. Their status must be reported separately from this remaining-case run and [original PR run 43036556295, attempt 2](https://github.com/oxo-ops/dkss/actions/runs/43036556295/attempts/2). The original [job 130583582383](https://github.com/oxo-ops/dkss/actions/runs/43036556295/job/130583582383) failed on Ubuntu package-host DNS before verification and has not been rerun by this work.

The original notification transport limitation remains: the verified notification GET uses a synthetic same-origin meta-refresh relay, not native HTTP redirect browser coverage. These results do not certify live AI/OCR accuracy, external delivery, production data, PostgreSQL concurrency, professional acceptance, all eight original workflows or full regression.

## Publication boundary

The validation branch must contain exactly:

1. `.github/workflows/pr377-supplemental-browser.yml`.
2. `README.md`.
3. `harness/validate_remaining.py`.
4. `harness/confirmation_acceptance.py`.

Preparation is not publication or test execution. Independent review must precede any validation-ref update. No product branch/main update, product PR, merge, deployment, credential or permission change is included. Only the dedicated validation branch push triggers this workflow; permissions remain `contents: read`.

After any separately authorized publication, verify the remote validation commit/tree and actual run outcome. Report failed, passed and never-run cases separately, including the original CI failure. Do not claim all acceptance passed merely because this workflow was prepared or a local HTTP-only reproduction passed.
