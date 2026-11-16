# Current parts card: share recorded-distance evidence policy

Baseline: main `1f37376f36f48741194f42aff5bad5ac00c24704`, tree
`e0c0f5494c3457172484c7479cfdc730f456cc90`.

Quality Word v15 requires maintenance/parts history, evidence and displayed
analysis to agree. #409 deliberately addressed history intervals only and left
current-state cards outside its acceptance. This follows that explicit gap,
not a restart of accepted M06 work or a duplicate of the analysis panel PR.

The current parts card previously subtracted the replacement meter from the
current meter without considering whether replacement was confirmed, whether
the parent's completion was future-dated, or whether same-day replacement
meters disagreed. A negative replacement meter could inflate the result.

Reuse the existing `replacement_distance` presentation policy already used by
the analysis panel. The card receives the scoped latest parent and same-date
meter ambiguity flag, and displays the policy's escaped hold reason. Imported
invoice actuals keep their existing factual contract even if the manual status
is incomplete. Genuine zero remains zero. No new formulas, thresholds, storage,
notifications, AI requests, schema or authentication changes.

Tests use disposable synthetic SQLite and actual Flask-rendered cards. Completed
and zero distance, unconfirmed work, invoice actuals, future completion, same-day
conflicts and negative meters are covered. Related history, shared projection,
and document connection tests also run.

- Combined: 31 tests, zero skips, OK in 3.854s.
- Independent: 6 tests, zero skips, OK; final review no blocker.
- Responsive static JS: three assertion groups passed; architecture inventory
  and diff check passed.
- Real Chromium visual check was attempted against localhost synthetic data but
  the browser failed before navigation: process_singleton socket Operation not
  permitted. No restriction workaround was attempted. The temporary server was
  stopped. Long reason wrapping/mobile visual acceptance remains unverified.

No main merge, deployment or production operation. Full CI is not yet run.
