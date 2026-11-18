# Search, masters and planner integration

Base: released c35ccb1fbbecf92a0efbb0bc34d73c3faeb57a88.

- #494 cf8a77c: compact driver/vehicle masters, search-only clearing and notification history restoration.
- #497 ba0cb304 (included by #500): distinguish filtered empty plans from empty periods.
- #500 fbd05a5: compact mobile planner actions, existing floating calendar-add design, plate-only new-plan choices, guide in normal/demo, annual one-axis panning and settling.

The two branches change disjoint product paths. This candidate retains the exact product bytes of both. Dedicated workflows run against this integrated HEAD using synthetic data only. No export builder, scope, recipient, permission or deploy guard change. Excel is unchanged. Real iPhone Safari verification is still outstanding; Chromium touch simulation is not physical-device confirmation. This draft is not deployed.
