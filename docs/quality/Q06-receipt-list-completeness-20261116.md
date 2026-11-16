# Q06: keep each recent document receipt intact

Scope: Word v16 §35.3 normal document intake; nonproduction only. Base main
`d05d3eb690c8b06d526518e25d8bc27f4b0bf609`; no open PR at initial check.

## Reproduction

Three still-reviewable receipts of 50, 50, and 2 originals produced counts
48, 50, and 2 in the recent intake list. `recent_imports` took the latest 100
individual draft rows before grouping by receipt. Older files within the
boundary receipt, including a read failure, could disappear from the summary.

## Change

Keep the existing latest-100-lightweight-row discovery window within the
same company and account-identity scope. Apply the same hidden/legacy metadata
visibility rules before selecting at most 12 receipt IDs, then fetch complete
eligible lightweight rows for those receipts. Retain existing pending/review/error eligibility, hidden-receipt
checks and status precedence. Source BLOBs remain excluded. No worker, AI,
POST, source-storage, permission or business-record mutation changed.

The list counts eligible outstanding rows, as before; it does not now claim
to count completed documents. The 12-receipt UI bound and 100-row discovery window are preserved;
only the selected receipts are expanded for accurate summary counts. This is
not a paginated all-history view and does not promise 12 receipts beyond that
discovery window.

## Evidence and limits

- Original regression reproduced 48 != 50 under the isolated SQLite/network guard.
- Queue module: 25 tests passed, including full boundary-batch count/error state,
  12-receipt limit and exclusion of other company/account-identity rows.
- Review found that limiting batches before Python visibility filtering could
  hide a valid older receipt behind 12 excluded candidates. Fixed by shared
  visibility filtering before selecting slots; regression includes legacy
  read-error/type-review metadata and hidden receipts.
- External AI mocked. No production DB, upload or OCR performed.
- PostgreSQL CI, independent review and real browser acceptance are separate.
