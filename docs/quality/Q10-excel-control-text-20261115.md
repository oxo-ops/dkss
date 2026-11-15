# Q10 annual inspection Excel text safety

Baseline main: 3627105d2b3e36a04e6cec9a56eb3747bc168d42.

Reproduced: `write_text` with a factory/note containing U+000B raises
`IllegalCharacterError`, preventing the entire annual workbook export. XML-invalid
noncharacters can also fail serialization. This is an export-only defect, not
proof of a production incident.

The shared annual-workbook text writer renders XML 1.0 forbidden code points as
visible `[U+XXXX]` text. Original stored values and event history are unchanged.
TAB, LF, CR and ordinary Unicode keep their existing behavior; formula-like values
remain literal strings, not executable spreadsheet formulas. No schema, permission,
notification, monitoring, AI request or production setting is changed.

Verification:
- Two pure round-trip tests cover forbidden C0 ranges, surrogate boundaries,
  FFFE/FFFF, Japanese/supplementary Unicode, tabs/newlines/carriage return and
  formula-like input. Compare valid text to the previous literal writer path;
  XML's existing CR normalization is not a new product change.
- Ten annual-export tests including a new real Flask/disposable-SQLite export
  check: load returned XLSX, confirm visible markers/formula safety, and verify
  source factory/note and event count remain unchanged.
- Final scoped run: 12 tests passed, no skips, network connections blocked and
  external-service environment values removed. Independent reviewer ran the two
  pure tests and found no blocking findings in code or route assertions.
- Initial broad module run executed 65 tests (including imported fixtures); one
  new assertion incorrectly expected XML to retain CR exactly. Test corrected
  to compare the baseline writer; production patch unchanged. The first run is
  not counted as fully passing.

No browser visual or real data acceptance claimed. No live export, DB access,
external request, PR merge or deployment performed for this change.
