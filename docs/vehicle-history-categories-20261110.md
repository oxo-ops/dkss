# Vehicle history category filters

The history page provides All, Inspection, Maintenance/Repair, and Other links with counts. Links work without JavaScript and expose selection and keyboard focus. Their minimum target height is 44px.

Counts cover all matching pages after the existing type, status, and date filters, but before the category filter. A category change returns to page one while preserving the other selected conditions. Pagination and page-size changes preserve the category.

Categories derive only from existing event types. Inspection, defect reports, periodic inspections, inspection scheduling/completion, and checklist actions are Inspection. Maintenance records, defect repairs, and unscheduled repair plans are Maintenance/Repair. Other recorded events, including driving reports, remain Other.

Unknown dates and distance are not filled with zero. Existing invalid-date responses, company/vehicle access boundaries, event ordering, and source links remain unchanged. No schema, import, permission, or analysis change is needed for this filter.

## Deferred event sources

Assignment-change history is not reconstructed from current assignment. Operation CSV rows contain import time and user fields but lack a direct source draft reference. Filenames alone cannot safely connect rows to source documents. Draft vehicle lists may be updated by later pending-record resolution, so draft completion time and creator cannot establish every vehicle's original import event.

Before introducing those histories, record immutable event identity, actual time/actor, and an authorized source relationship. Do not infer historical events or expose user-private source drafts as company-shared records.

## Validation

Focused category tests and the integrated local regression passed, with explicit database/browser skips. Hosted database and real-browser acceptance remain required. No production migration or deployment is included.
