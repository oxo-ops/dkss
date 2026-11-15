# Q06: bounded OCR numeric normalization

Scope: driving-report OCR candidate normalization only. Baseline main
`0a0429f5794915a04e8bba1841628a49c2d9d9de`.

A short input such as `1e-10000` previously produced 10,002 characters through
fixed-point formatting. Larger exponents could cause unbounded allocation before
strict field validation. The change computes the formatted length from the Decimal
tuple before formatting, matching existing distance (50) and item numeric (100)
text limits. No rounding, unit conversion, fabricated zero, schema change, or
change to ordinary accepted values is introduced. Oversized candidates take the
existing invalid-value path: typed value is null, item status unknown, original
value and review issue remain available.

Verification (non-production):
- Five focused tests: exact signed/unsigned boundaries, zero distance scale,
  existing formatting, rejection before format, and original preservation in all
  four item collections.
- Existing OCR validation and AI transport fixtures plus new tests: 19 tests,
  no skips, passed with Python 3.12.14. Network connections blocked; credentials
  removed; actual Flask fixture uses a disposable SQLite database. AI transport
  is mocked, no AI call or charge.
- Added Flask route regression uses real field definitions and strict validation,
  then upload, preview HTTP 200, confirmation and persisted JSON to verify original
  text remains reviewable while the numeric fact is absent.
- Independent reviewer found no blocker, ran five focused tests, and compared the
  length calculation to real formatting across 3,609 coefficient/exponent cases.
  Added route test also independently reviewed.
- Initial default Python lacked Flask; seven pure validation tests passed but
  route setup failed. The subsequent dependency-equipped isolated run above is
  the successful result, not a claim that the first run passed.

Not claimed: full repository regression, browser/device visual acceptance,
production login, real OCR request, live deployment. No production changes.
