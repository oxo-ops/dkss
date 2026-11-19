# Scoped integration on Live 544

Base: 463894aac8cad65b9b28ffe0a1d354359b1d1050.

Included exact accepted sources:
- 549 2ff8fd42d2015999fa97ea9c66fcbaa72c2a030a: unselected demo planner notice overlap.
- 550 a3412cccf00aeea7ecde3c0a4a5e6bcd86a36387: safety records reading rows and slanted blue tabs.
- 551 d9dba6479da5363320ac5e913b8cded46505c905: daily report mobile density and blue accents.
- 552 2356c8d5b27869214aa1d33dfd0165c365075a32: safety heading add placement and nonsticky detail title.
- 553 c1f0a913f2c1f2554407804588f58efdc3e3ba84: three Excel controls and unchanged download routes.
- 554 66efb53703d000dc9522b649adba3ed48953c57d: stable driving filter trigger.

Each source completed its CI before inclusion. Integration is NOT accepted until its own CI and actual browser artifacts pass.

Conflict resolutions: driving_reports retains compact stylesheet plus filter JS and newer workspace stylesheet. checklist_result_detail retains BOTH normal-scroll flow stylesheet and Excel stylesheet. No source feature removed. Seven dedicated browser workflows target this integration branch.

Excluded: 555/556/557/558/559/560 and master toolbar work. Later success does not automatically expand this scope.

No database, authentication, production settings, deployment or guard changes. Native local browser is blocked by container socket permissions; isolated CI is the browser verification path. Real iPhone/Teams remain unverified.
