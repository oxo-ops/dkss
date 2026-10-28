# Q07: existing maintenance dates and cost buckets

## Problem

A stored arrival date such as `2026/10/28 12:00:00` was accepted by the
company dashboard's shared cost-date reader, but excluded from the vehicle's
annual and monthly cost summaries. The cumulative amount still included it,
so different views of the same record could disagree.

## Change

Vehicle cost details and annual summaries now use `maintenance_facts.cost_date`,
the same reader as the dashboard. ISO dates, legacy slash dates, and stored
timestamps therefore use the same date bucket. Empty arrival dates retain the
existing completion-date fallback. Invalid nonempty arrival dates remain
undated; zero and unknown amounts remain distinct. No stored values are rewritten.

This does not change invoice confirmation, document originals, work completion,
or rules for assigning historical costs to an office. The dashboard continues
to show only the offices and date periods selected by its existing rules.

## Verification

Before the fix, the reproduction asserted dashboard cost 500 and vehicle annual
cost 500 for the same legacy-dated row; the latter returned `None`.

Four added isolated application tests cover:

- ISO, slash, and timestamp dates; dashboard/month/year agreement and cost page rendering.
- Empty arrival date with a legacy completion date.
- Invalid calendar date retained as undated without inventing a replacement.
- Zero versus unknown costs in the same legacy month.

Related regression tests also cover document import/replay, original access,
vehicle overview, analysis, and maintenance context. These checks use local test
DBs and do not require real customer records or external AI calls.
