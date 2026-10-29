# Application structure and operations

Current startup/settings/stop and CI investigation instructions are collected in
[the runtime operations guide](runtime_operations.md). The no-DB-write claims
below describe factory/import behavior. The current Gunicorn `post_worker_init`
also initializes driving readership and coupling storage before starting OCR;
it is not a read-only schema check or a replacement for all explicit migrations.

This change replaces the application-wide monolith with an application factory,
unbound extensions, separate model definitions, explicit route registration,
and business responsibility modules. It includes the previous, unmerged
analysis-summary extraction, so that script does not need to be applied separately.

## Entry points and initialization

- `app.py` remains the WSGI entry point (`gunicorn app:app`) and the local Flask
  entry point (`py -m flask --app app run`). Existing URLs and endpoint names remain.
- `dkss_app.create_app(config=None)` builds an application without connecting to,
  initializing, migrating, or seeding the database. Importing the package does
  not create an app. Importing `app.py` builds registrations, without DB writes.
- `dkss_app/extensions.py` defines unbound SQLAlchemy, CSRF, and rate-limit objects.
- `dkss_app/models.py` defines the 43 core models. Integration model modules cache
  their 14 model definitions per SQLAlchemy extension, preserving table identity
  across factories without duplicate declarations.
- Existing compatibility migrations and bootstrap are in `dkss_app/database.py`.
  Run them explicitly, once, using `py -m flask --app app init-db` when a new or
  older database requires initialization. They no longer run in every web worker
  or when a maintenance script imports the application. This restructuring adds
  no tables, columns, constraints, indexes, or automatic data migration.
- `create_app(initialize_database=True)` is available for isolated fixtures;
  production web startup uses the default `False`.

For a new local database:

```powershell
py -m flask --app app init-db
py -m flask --app app run --host=0.0.0.0 --port=5000
```

For an existing initialized database, the run command is unchanged. In deployment,
execute any required schema/bootstrap step before starting web workers, rather
than relying on module import. The existing initialization command requires
`ITC_INITIAL_PASSWORD` only when the initial administrator does not already exist.
Never point regression tests or benchmarks at production data.

## Responsibilities and dependencies

`routes.py` only registers HTTP handlers, error handlers, template filters, hooks,
and CLI commands. It preserves the original decorator order, endpoint names,
methods, authentication hook order, CSRF behavior, and limiter declarations.

The business modules cover authentication/access, audit, company/master data,
notifications/delivery, dashboards, safety, patrols, checklists, file storage,
vehicle master/import/pending records, vehicle cards/documents/costs, maintenance
knowledge, and analysis. Function bodies refer to their defining modules
explicitly; implementations never import the compatibility `app.py` entry point.

`common.py` contains shared imports and immutable constants, not a mutable copy
of the application's function namespace. Environment-dependent values and
integration services are resolved from the active application's configuration
and extension state. `integrations.py` declares the dependencies passed to the
existing integrations. Vehicle overview and document deletion no longer receive
`globals()`. Withdrawn-source feedback filtering is an explicit query-result
policy rather than a registration-time replacement of a global function.

Inspection synchronization registers one SQLAlchemy dispatcher per extension/model.
It selects the current app's service and session, so creating a second app neither
captures the first app's configuration nor duplicates transaction callbacks.

`compat.py` retains read access to old `from app import Vehicle` and helper names
for existing scripts. It is a compatibility boundary only; implementation modules
do not use it. Existing test assertions use a test-only adapter that patches the
actual defining module. No existing assertion or scenario was removed.

## Validation

- All 189 original URL rules, endpoints, methods and slash behavior match.
- All 57 ORM table definitions, PostgreSQL table DDL and declared indexes match.
- Request/response/context hooks and template filter registrations match.
- AST comparison matched the original logic of 452 function/class definitions
  after removing namespace qualifiers and moving decorators. The two deliberate
  differences are explicit overview dependency wiring and source-withdrawal
  filtering previously installed by document deletion.
- Analysis summary/mileage outputs matched the old implementation on 200 seeded
  datasets; 13 independent aggregation contract tests are retained.
- Eight architecture tests cover import/factory without DB connections, exact
  registration/schema parity, distinct app engines/config, explicit bootstrap,
  per-app inspection synchronization, dependency direction and unresolved names.
- Full suite: all 322 tests passed (314 existing/aggregation tests plus 8 architecture tests).

## Limits and further engineering

This resolves application construction, schema-on-import, model identity,
registration and whole-namespace coupling. It does not claim every business
function is now small or every business dependency is independent: checklists
and vehicle imports still have long workflows and cross-domain calls, now located
in their responsibility modules. Existing transaction semantics are retained.

The command retains existing compatibility migrations; introducing versioned
schema migrations is a separate behavioral/operational change. PostgreSQL DDL
compilation checks model parity, not live production schema or concurrent locking.
This work does not by itself establish AI response time, production worker setup,
200-user capacity, penetration-test results, backup restoration or recovery time.
Those require measurements and operational validation. No new infrastructure,
queue product, framework or dependency was added.
