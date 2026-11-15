# Q07: cost comparison completeness notes

Base: official main 71baf270 (local equivalent 603d984, tree 42d9f4d47cbcdf2f5dd329e9e23948482214c79b).

## Finding
The costs page explains missing amounts in the selected year, but the previous-year comparison and all-time card can silently exclude additional missing amounts. For example, current 200 against previous known 100 plus an unknown entry displays +100% without disclosing the previous-year gap.

## Scope
Add scoped missing-amount counts and adjacent plain-text notes for the previous-year and all-time cards. Existing totals, ratio formula, handling of zero, date filtering, factual-source exclusion, company/vehicle restriction, and stored records are unchanged. No schema, auth, background job, external API or production changes.

## Verification
- Three new real Flask/temporary SQLite tests cover previous missing amount, undated cumulative amount, zero and excluded synthetic/foreign records.
- New tests plus existing cost display/date suites: 14 tests, no skips, passed.
- Responsive static checks (3 groups), architecture inventory, generated schema equality, diff check passed.
- Related analysis/domain suites: additional 30 tests, no skips, passed.
- Independent review: no blocking finding; reviewer independently passed the three new tests and diff check. No full CI, real-browser visual acceptance, production business acceptance, publication, merge or deployment performed.
