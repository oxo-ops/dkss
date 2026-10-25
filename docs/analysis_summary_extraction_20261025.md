# Analysis fact aggregation extraction

Based on main after PR #153 (`6f7350bb76234d67a8bfd8220f7799f001981620`).

`VehicleAnalysisSummaryService` in `vehicle_analysis_summary.py` owns the
existing mileage reference selection and analysis summary calculations.
The existing two app functions keep their names and signatures and delegate
to the service. Source exclusion policies and the Japan-local current date
are explicit constructor dependencies. The service imports no app, Flask,
or SQLAlchemy and performs no database queries or external requests.

Preserved contracts:

- Missing cost and distance remain unknown rather than becoming zero.
- Cost per kilometre requires known values, positive distance, and matched months.
- Source exclusion follows the existing maintenance parent and company/vehicle keys.
- Explicit synthetic periodic sources remain excluded.
- Recorded distance remains distinct from a verified current measurement.
- Same-day conflicting readings, decreases, future dates, invalid numbers,
  and readings after the requested reference date keep their prior treatment.
- Source identifiers, exclusion evidence, monthly/category totals and output keys
  retain the original form, including Decimal values.

Validation:

- 13 independent service contract tests use plain record objects without app startup.
- A deterministic comparison of 200 generated datasets against the original
  functions matched the complete summary and mileage outputs, including points.
- AST comparison confirmed every other existing top-level function and model
  unchanged, including route decorators. No template, JavaScript, CSS, URL,
  model or schema changes.
- Full regression suite: all 314 tests passed.

This stage separates aggregation responsibilities. Peer comparison, knowledge
application and evidence builders remain subsequent work. Production AI,
PostgreSQL concurrency, and concurrent load tests are outside this validation.
