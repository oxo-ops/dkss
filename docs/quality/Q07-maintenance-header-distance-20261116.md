# Maintenance header elapsed-distance evidence

Word section 35.3: do not present an elapsed distance when the source meter is invalid. The common vehicle header previously showed 1,600 km for a current meter of 1,500 km and a legacy maintenance meter of -100 km. The actual authenticated GET reproduced this in disposable SQLite.

The narrow fix checks both values are finite, non-negative and non-decreasing before subtraction. Legacy records and raw displayed source values are not rewritten. Known starting zero and known zero elapsed distance remain valid. Existing source-date and mileage-reference gates stay unchanged. No schema, authorization, cost, notification or production configuration change.

Baseline: main 98930b3378c2a3e37e0399a858dfa57edb1939b7, including #430, #431 and #432. The independently reviewed original runtime patch applies without conflict. Final focused tests on this baseline: 29 passed, 5.763s, with outbound sockets prohibited and a disposable SQLite database. Independent review found no blocker and independently reran the five new tests (1.887s). Non-finite values were statically reviewed; real PostgreSQL non-finite behavior and real-browser acceptance are not claimed.

Current Live ef855318 and release candidate #433 eeaffa7a retain the same affected arithmetic block. This branch is a follow-up candidate; it does not alter #433, deploy, update startup guards, or claim production acceptance. Full CI is tracked on this PR separately.
