# Maintenance timing: bound calendar periods before integer conversion

Baseline: main `3627105d2b3e36a04e6cec9a56eb3747bc168d42`.

The quality-improvement Word v15 keeps accepted M06 and prior date-quality work
closed and asks for traceable maintenance facts/priority evaluation. This is a
new, narrow defensive arithmetic finding, not a reopening of those completed
workstreams or proof of a live incident.

The shared replacement/inspection timing service accepted finite positive
Decimal periods and called `int(threshold)` before rejecting dates beyond year
9999. Compact exponent notation can therefore expand into an unnecessarily
large integer. No claim is made here that an unauthenticated caller can reach
that value through current import/adoption validation.

The fix compares against the exact remaining days/months to `date.max` before
integer conversion. Outside-range values retain the existing `unknown` /
`calendar_date_out_of_range` result and cannot assert that maintenance is due.
Valid dates, month-end clamping, evidence matching, relation rules, distance
criteria and engine-hour handling are unchanged. No schema, source record,
authentication, notification, AI request or production operation is changed.

Regression tests cover both actions, both calendar metrics, compact Decimal
and finite-float extreme values, the exact final representable date, and one
unit beyond. A scoped integer-conversion sentinel detects premature expansion
without actually constructing the enormous integer. Inputs remain unmodified.

Local verification (Python 3.12, isolated synthetic fixtures):

```
PYTHONPATH=.:tests AWS_EC2_METADATA_DISABLED=true python -m unittest \
  test_maintenance_timing test_q05_additional_boundaries \
  test_priority_adopted_timing -q
Ran 45 tests in 3.486s
OK
```

All 45 ran; no skips. Full CI and production acceptance are separate. This
change does not establish full quality-program completion or release approval.
