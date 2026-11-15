# Inspection planning: exact target identifiers

## Scope and evidence

Follow-up to quality plan Q02 (request/tenant boundaries) and Q08 (invalid state/input rejection), checked against main `3627105d2b3e36a04e6cec9a56eb3747bc168d42` on 2026-11-15. Existing completed company-boundary work is not reopened or counted again.

Inspection planning used Python `int()` directly on JSON identifiers and versions. A fractional ID such as `1.9` or boolean `true` could select integer ID `1`; a very large integer could reach SQLite and return HTTP 500 (`OverflowError`). This is not evidence of cross-company access: existing company predicates remain enforced. It is an exact-target/input-validation defect.

A bounded integer parser now rejects booleans, floats, containers, negatives, and values beyond signed 64-bit SQLite binding range (not a change to model column capacity) before lookup. Required IDs are positive; optional links and versions retain omitted/null/empty/zero behavior. ASCII digit strings remain supported. Whitespace, plus-prefixed, and Unicode digit strings previously accepted by Python int() are now rejected. The bundled static/js/vehicle_inspection_plans.js uses server-provided integer IDs/versions, null/0 defaults, and standard ASCII form/select values (lines 45, 105, 126, 194–195, 591, 614); no external API contract promising broader numeric coercion was found. The same validation covers plan preview/save, execution preview/save, detail/scope reads, and execution-original path IDs. No schema, authentication, notification, or production setting changes.

## Verification

- Before fix: 5 new synthetic Flask/SQLite tests ran with 28 failing subcases, including fractional/boolean acceptance and oversized-ID HTTP 500.
- Final focused suite: 8 new tests plus 77 existing inspection-plan, date, and company-boundary tests. Includes rejecting a fractional vehicle ID with an otherwise valid preview token, checking no plan/event is written, preserving integer strings, and rejecting oversized original-file path IDs.
- PostgreSQL CI adds eight real-route tests in a loopback-only disposable PostgreSQL 18 schema, checks actual integer column types, and checks int32-exceeding/int64-boundary comparison parameters. Local execution skips without its dedicated test URL; PostgreSQL success is not yet claimed.
- Unit/route tests do not constitute real browser or production acceptance. CI integration remains separate.

## Delivery

Non-production candidate. Draft PR review and exact-head CI must precede merge/deployment. No live database connection, notification delivery, or production resource operation was performed.
