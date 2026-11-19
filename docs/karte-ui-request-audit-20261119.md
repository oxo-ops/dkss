# Vehicle karte UI request reconciliation

Baseline: Live 6ca81bc (local adc6cbc has identical tree), 2026-11-19.
Evidence: user IMG_2286 (Library libfile_d7c456be646c819187cc7ac4050cc90e), current templates/CSS; previous #521 exact integration browser images. Older 79 audit is not a current completion list.

| Area | Reflected in Live | Remaining / verification boundary |
|---|---|---|
| Common, eight tabs | compact identity disclosure; magnifier and input clear; header icon layout | import/list/edit row still occupies mobile space; all-tabs visual simplification not complete |
| Overview | common header; saved proposals and existing original/detail routes | confirmed duplicate maintenance action button, proposal detail button, plan button rows. This patch targets these only. Overview/history same thin list and date requirements need further reconciliation |
| History | mobile four columns date/kind/content/status; history opens in-app detail instead of immediate PDF | persistent filter/category/header height; real iPhone unverified |
| Inspection | mobile abbreviated dates | multiple wide tables and permanent filters remain; full list-density redesign not complete |
| Maintenance | abbreviated dates and duplicate date omission; in-app details with source action | filters and table density remain to review |
| Parts | common compact header | seven-column exchange history/current sections not fully redesigned |
| Costs | common compact header | selected-period summary/graph density not fully reconciled |
| Documents | mobile five columns, PC eight columns; date shortening | closed-preview paging fix is #531, not yet Live; PDF content readability outside synthetic fixture QA |
| Analysis | common header; guide timing latest fix | proposal/graph/period tool density to reconcile; do not alter advice or source data |

The pictured duplicate action buttons are a genuine unimplemented request, not a stale screenshot/cache claim. Preserve all links, permissions, status warnings and plan-dialog attributes. No DB, authentication, deployment or settings changes.
