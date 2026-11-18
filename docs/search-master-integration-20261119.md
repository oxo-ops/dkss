# Search and master follow-up integration

Base: released c35ccb1fbbecf92a0efbb0bc34d73c3faeb57a88.

Included candidates:
- #489 57c5f254: compact driver/vehicle lists on mobile, details disclose existing fields; desktop tables remain.
- #490 7fcecb2f: query-only clear for safety patrol, maintenance records and checklist master.
- #492 64da07ef: notification query-only clear versus explicit all-filter reset; history restoration; filtered zero-result language.

The readership test in #489 is byte-identical to the released base and is not an additional modification.
No validation guard, permissions, recipient resolver or POST action changes.
Plan empty-state follow-up #497 is deliberately excluded.

Acceptance on the integrated HEAD:
- Master Compact Browser
- Search Clear Browser (master query fields)
- Search Cross Browser
- Notification Search Browser (GET snapshots, Back, empty results and reset)
- Existing PR regression, Q10 and dependency checks
- Pixel inspection of integrated screenshots

Synthetic isolated fixtures only. Native device IME is not verified; GET snapshot tests are not live production writes. An isolated PASS is not a deployment. Publication remains a separate reviewed step.
