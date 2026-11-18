# Search experience follow-up audit

Base: release integrated c35ccb1. Independent follow-up; not a blocker for #488.

## Confirmed current behavior and remaining acceptance
| Surface | Input / erase / cancel | Empty results / conditions | Priority |
| --- | --- | --- | --- |
| Inspection plans | Existing instant search, clear text, cancel restores starting query | Verify native IME, older responses, detail-close focus and year/view/office preservation | A |
| Karte vehicle search | Header dialog; input clear distinct from closing; input focus retained | Synthetic tests passed in #488. Real IME, delayed/no results, resize still need acceptance | A |
| Driver / vehicle masters | GET search; per-field clear keeps selects/hidden; compact UI in #489 | Actual GET/back and native IME remain; no implicit live search added | A |
| Safety patrol pointouts | GET keyword; no text-only clear previously | Existing office/status/category/dates and type/page-size hidden values must remain | A: this candidate |
| Vehicle maintenance patrol list | GET keyword plus status; no text-only clear previously | Existing usage-vehicle selector is a separate POST selection, explicitly excluded | A: this candidate |
| Checklist master | GET keyword plus target/status; full reset labelled ambiguously | Existing no-match state; all-condition reset retains original URL | B: this candidate |
| Notifications | Search input native clear; adjacent x resets q/category/type together | Needs explicit distinction between text clearing and all-filter reset; view must remain | A: next candidate |
| Karte documents | GET q/kind/period/uploader; native text clear; reset clears filters | Preview and document_url carry filters. Verify clearing vs resetting and back | B |
| Karte parts | GET q, category/status filter chips have individual remove links | Verify clear scope and no-results; do not replace existing chips blindly | B |
| Driving reports | Main template delegates filters to partials | Detailed partial audit still pending; no completeness claim | B |
| OCR searchable selection / usage vehicle selection | Selection rather than ordinary list search | Query clearing must invalidate selected ID appropriately; needs separate tests | C, not included |

## Scope of this candidate
- Three explicit keyword fields only. Reuse existing search_field_clear with narrow selector allowlist.
- Clear changes only the text input and emits input, focuses input, never submits.
- Other FormData and destination, role/company authorization, mutation forms unchanged.
- Checklist full reset label clarifies all-condition reset; URL unchanged.
- 3 actual synthetic Flask GET pages x 4 widths planned. No real account data, secrets, remote POST or AI.
- Native IME, real GET/back/history, failed/slow requests and all-page audit are not yet complete.
