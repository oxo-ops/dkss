# PR377 supplemental browser validation

This branch is a disposable validation harness, not a product branch or a replacement for the original PR checks. It provides supplemental acceptance evidence for three directly relevant browser workflows, not a replacement for all eight original workflows or the full backend regression. Do not open a product PR, merge, deploy, or move PR377's branch from this work.

## Frozen application

- Repository: oxo-ops/dkss.
- Application commit: 30d4dfeee97f69bd00650c6bf56a5ce234f34437.
- Application tree: 31bb88b2d7a1a93f4c52f5aeefd59e97a8c8d3ea.
- Requirements blob: f29b6951157ecb12ef81490f42dfb5d57bdd9330 (38 exact pins).
- Original workflow: https://github.com/oxo-ops/dkss/blob/30d4dfeee97f69bd00650c6bf56a5ce234f34437/.github/workflows/common-priority-browser.yml
- Original run: https://github.com/oxo-ops/dkss/actions/runs/43036556295/attempts/2
- Original failed job: https://github.com/oxo-ops/dkss/actions/runs/43036556295/job/130583582383

The original job failed during Playwright system dependency installation because Ubuntu package hosts did not resolve. It did not reach HTTP/browser verification. A passing supplemental run does not change that original job conclusion and must be reported separately.

## Official dependency image

The official Microsoft Artifact Registry UI was checked on 2026-11-11:

- Tag: mcr.microsoft.com/playwright/python:v1.62.0-noble.
- Published: 2026-08-01.
- Immutable manifest-list digest: sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d.
- Listed amd64 image digest: sha256:51d31fdfacb0cff99a1a724152e34ae408d2bd4e7da310ff157450f49261cc59.
- Registry: https://mcr.microsoft.com/en-us/artifact/mar/playwright/python/tag/v1.62.0-noble
- Official versioned Dockerfile: https://github.com/microsoft/playwright-python/blob/v1.62.0/utils/docker/Dockerfile.noble
- Official explanation: https://playwright.dev/python/docs/docker

This vendor image already contains the version-matched browsers and OS libraries. The workflow does not run apt, install-deps, playwright install, or a mirror/proxy/DNS workaround. It uses the official GitHub-hosted ubuntu-24.04 runner with the default container security configuration. It adds no privileged, capability, seccomp, host-network, IPC, or DNS flags. The image's default user is root; no browser launch flags or sandbox settings are changed from the existing Playwright harnesses. The vehicle comparison harness already explicitly includes --no-sandbox, which is preserved without modification. These tests use only the existing synthetic fixtures and request bridge, not arbitrary websites.

## Runtime differences and provenance

The original job log records CPython 3.12.16 on GitHub's ubuntu-26.04 runner image 20261101.186.1. Its included-software manifest lists Node 24.22.2:
https://github.com/actions/runner-images/blob/ubuntu26/20261101.186/images/ubuntu/Ubuntu2604-Readme.md

The supplemental container uses Ubuntu 24.04's Python 3.12, whose exact patch/build is recorded at execution; it is not claimed to be identical to CPython 3.12.16. Global virtualenv is already in the official image, so it creates the isolated environment without installing python3-venv or running apt. The Playwright Python package is separately installed at exactly 1.62.0, as required by Microsoft's image documentation.

The official setup-node action is pinned to commit 249970729cb0ef3589644e2896645e5dc5ba9c38 and selects Node 24.22.2, with package caching disabled. Checkout and artifact actions use the immutable action SHAs recorded in the original run. Package downloads use ordinary HTTPS from official PyPI, with pip's isolated configuration. All 38 requirement versions and Playwright's version are asserted after installation; pip check, a package freeze, pip's installation report, and a full runtime manifest are retained.

The application is checked out into a new application/ subdirectory owned by the container execution user. This lets the unchanged env -i wrappers use Git's normal ownership checks with fresh HOME directories, without safe.directory exceptions, ownership changes, or weakening the isolation wrappers. Source commit, tree, requirement blob and cleanliness are checked before execution; source commit, tree and cleanliness are checked again afterward.

## Coverage preserved

The workflow runs the original, unmodified files from the frozen application commit:

- Node contracts: vehicle_periodic_priority_js.cjs, vehicle_priority_confirmations_js.cjs, vehicle_priority_presentation_js.cjs, vehicle_karte_overview_js.cjs.
- Three HTTP-only preflights: confirmation_manufacturer, confirmation_legal, confirmation_progression.
- Thirteen common-priority browser invocations: common; stage2 instruction/recheck/timing; connected normal/instruction/recheck/invoice/periodic_instruction/periodic_timing/confirmation_manufacturer/confirmation_legal/confirmation_progression.
- Original vehicle-comparison browser harness, from .github/workflows/vehicle-comparison-browser.yml, with its existing CSP and no-JavaScript coverage.
- Original dashboard-saved-proposals browser harness, from .github/workflows/dashboard-saved-proposals-browser.yml.

Every original env -i wrapper and its Python network/SQLite guard remains unchanged. Each browser uses the official image's existing executable by absolute path, as the original --chromium interface requires. The aggregate step requires all 3 HTTP + 13 common-priority browser reports, plus the comparison and dashboard reports, the exact application commit/tree, and synthetic-only/no-production assertions. It does not replace assertions or weaken failures. The connected harness's explicit limitation remains: the verified notification GET is bridged via a synthetic same-origin meta-refresh relay, not a native HTTP redirect browser transport test.

Evidence is uploaded as three separate supplemental artifacts (common/runtime, comparison, dashboard), with 14-day retention, even after a failed test when evidence exists. Comparison and dashboard are independent steps after runtime verification and can still run when another test fails; no failure is ignored. All three acceptance groups must succeed for the aggregate summary. The common artifact's absence is an error; missing comparison/dashboard artifact uploads warn, but cannot turn an unexecuted or failing test into an aggregate pass. The workflow's own commit and target application commit are separately recorded.

## Publication boundary

Only this README and .github/workflows/pr377-supplemental-browser.yml should be in this validation branch's tree. Avoid inheriting other workflows so a push cannot trigger unrelated repository tasks. Create the exact branch validation/pr377-browser-30d4dfe-container only after independent review. Its push trigger needs no default-branch workflow change, new PR, manual workflow-dispatch entry, secrets, or write permissions. The only repository permission requested is contents: read; checkout does not persist credentials.

Preparation of these blobs is not publication or test execution. The publisher must verify the remote branch tree and resulting run, then report actual outcomes, runtime differences, artifacts and any remaining original-CI failure. Do not call the application merge-ready on the basis of an unexecuted workflow.
