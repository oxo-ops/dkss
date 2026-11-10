# Dashboard saved-proposal acceptance

This is a narrow synthetic acceptance suite for the dashboard's saved maintenance
recommendations. It does not calculate priorities or generate recommendations.
The first five existing candidates in each current group are shown, with the
rest available through native details. Known saved high/medium/low labels are
shown; unknown values do not become a fourth label or an invented priority.

The runner uses a disposable SQLite fixture and a real Flask GET response bridge
to Chromium. Python network connections and existing SQLite files are forbidden
by the existing history-browser guard. Browser requests outside the synthetic
origin and all non-GET requests fail the test. Credentials and external services
are not inherited. No live HTTP/TLS, real login or production acceptance is claimed.

The exact candidate SHA and clean worktree are required. The six viewport cases
cover 1440, 1180, 900, 768, 390 and 320 px; the first and fifth rows must be reachable
without an internal vertical scroll limit, both groups retain exact remaining
counts, repeated pointer/keyboard expansion works, and page width stays bounded.
Back/Forward and native details without JavaScript are also checked. Original
screenshots and measured geometry are retained for independent visual review.

Saved analysis records and feedback are unchanged. Existing dashboard usage
summary updates and the known notification-maintenance writes are explicitly
bounded by endpoint/table/verb and reported. The ordinary app is not globally
read-only. No retries are performed after a failed or blocked browser run.

Local preflight uses `run-isolated.sh ABSOLUTE_REPO ABSOLUTE_PYTHON
--expected-sha FULL_SHA --preflight-only`. It does not start a browser and is not
browser acceptance. The dedicated PR workflow runs Chromium on the exact head.
