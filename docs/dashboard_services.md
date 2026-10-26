# Dashboard responsibilities and verification

The previous `dashboard()` mixed request settings, SQL, repeated score interpretation,
checklist aggregation and template assembly in one 1,652-line handler. The new handler
coordinates explicit request-scoped dependencies and renders the existing template.

| Component | Responsibility |
| --- | --- |
| `DashboardScope` | Resolve the actual user's office, saved display settings and inclusive/exclusive date bounds. A saved office preference never widens office scope. |
| `DashboardRepository` | Query company-scoped records, load referenced vehicles in batches and group assigned-vehicle results by checklist and vehicle. Caches live for one request only. |
| `DashboardScoring` | Interpret numeric/symbol answers and each item's maximum. Eight repeated scoring loops now use this one policy. |
| `DashboardService` | Build ranking, personal summaries, category/item/target analyses, setup links and vehicle summaries. Formatting callbacks and history lookup are passed explicitly. |
| `dashboard()` | Record usage as before, capture request identity/date, wire components and supplemental panels, and render `index.html`. |

## Boundaries kept

- Every repository query limits records to the current company.
- Office-wide panels use the actual user office. An unassigned office yields empty
  office results rather than all-company results.
- Personal vehicle panels still follow assigned vehicles, including assigned vehicles
  at another office. Deleted and foreign-company vehicles remain excluded from that
  personal panel. Historical target lookups retain their existing treatment of deleted vehicles.
- Personal-name target breakdowns remain restricted to `admin` and `itc`.
- Vehicle checklist results use the saved snapshot when present. Safety checklist
  aggregation retains its existing rules; this refactoring does not change scoring policy.
- Period boundaries, rounding, result URLs, labels and output fields remain unchanged.
- Usage-recording writes, routes, hooks, templates, CSS, JavaScript and ORM schema are unchanged.

## Verification

The previous handler was executed from the parent source against the same isolated
SQLite fixture as the new handler. All captured output fields matched in seven cases:
admin, regular user, ITC, no office, another office, 7-day period and invalid-period fallback.
The unchanged maintenance-cost helper's current-month output is excluded from the
permanent fixed-date JSON fixture; it is included in the rendered-HTML comparison.

| Fixture / role | Previous SELECTs | New SELECTs |
| --- | ---: | ---: |
| Base / admin | 48 | 38 |
| Base / regular user | 45 | 35 |
| Base / ITC | 42 | 32 |
| Base / no office | 34 | 30 |
| Base / Osaka office | 43 | 37 |
| Base / 7-day period | 40 | 36 |
| Base / invalid period fallback | 48 | 38 |
| Base plus 80 vehicle results / admin | 128 | 38 |

These counts cover the direct dashboard handler, including its supplemental helpers.
They are fixture measurements, not latency guarantees or production concurrency tests.
The rendered HTTP response for the larger fixture matched byte for byte (112,573 bytes),
including normal request hooks after initialization. No browser screenshot comparison
was performed because the template and assets were not changed.

Full regression result: 371 tests passed in the isolated environment.

Five permanent tests cover fixed output contracts, company/office/assignment and
personal-name boundaries, SQL growth when adding results, cache lifetime/update
visibility, missing drivers and score-symbol interpretation.

Run `python -m unittest discover -s tests -p test_dashboard_service.py -v` for the
focused checks, and `python -m unittest discover -s tests -v` for all regressions.
All test data is isolated; no production database, API, credentials or external messages
are involved.

## Remaining work

Supplemental panel helpers in `dashboard.py` retain existing SQL and are outside this
change. There is no claim that every dashboard query is optimal or that all scans have
been eliminated. PostgreSQL query plans, concurrent access and Render worker behavior
still require separate measurement. Large checklist workflows and Excel exports remain
separate refactoring targets.
