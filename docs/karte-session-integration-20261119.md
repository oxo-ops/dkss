# Follow-up integration: vehicle record and session recovery
Base: released b97bdf01f920d3cd985dc26633ec36d0f8f8cf71. No Render or Live changes authorized by this branch.

## Sources (all exact-head individual checks passed before integration)
- #519 fae1794a: safe same-GET recovery after demo session loss; no POST replay, minimum driver role, original query retained, ordinary account boundary unchanged. 12 checks.
- #514 7dab19ef: mobile short dates, duplicate maintenance date suppression; desktop original dates retained. 7 checks.
- #515 0b412469: desktop icons/search interaction parity; existing destinations and permissions unchanged. 17 checks.
- #516 e0cf9baf: compact mobile common vehicle identity/8 tab header. 7 checks.
- #518 d8b787dc: mobile document list density; desktop8 columns and original links maintained. 7 checks.
- #520 9d4c549d: history first click opens existing maintenance detail, not raw source; original source remains separate. 16 checks.

## Integration decisions
Vehicle header keeps both date and compact identity assets. Base keeps released title/responsive/entry asset versions and adds desktop actions without reverting b97. Browser header tests retain released78-case title/guide checks plus desktop search and master filter interaction checks. Driving browser manifest recalculated only for reviewed combined base.html. Five dedicated browser workflows enabled for this branch; normal pull-request session/aggregate gates remain.

## Verification before push
Python mobile-date3/session-recovery12/history-category6 tests passed. JavaScript syntax and git diff whitespace checks passed. Integrated browser, permissions, aggregate regression and actual screenshots are pending. Individual success does not imply integration success. Real iPhone/Teams not tested.
