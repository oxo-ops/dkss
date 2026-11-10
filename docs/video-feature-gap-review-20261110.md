# Vehicle overview and priority preview acceptance

## Candidate scope

- Overview renders at most five saved maintenance recommendations in saved priority order, with accessible detail links.
- History adds inspection, maintenance/repair, and other category filters with counts. Only recorded events are used.
- The experimental numerical priority preview is synthetic-only, explicitly opt-in, and disabled on production. It does not change saved recommendation identity, revision, feedback, or priority.
- Preview HTML and result retrieval avoid last-view persistence, AI generation, and read-cache writes. Normal operational forms remain unchanged; the entire application is not read-only.
- Preview navigation preserves the mode across analysis/overview, period/comparison, and vehicle selection.
- TLS certificate tests compare exact certificate membership without weakening hostname or certificate verification.
- Dependency pins update pypdf, boto3, and botocore. A current hosted vulnerability audit remains required.

## Boundaries

The numerical score is a trial design, not a manufacturer-certified probability of failure. Evidence insufficiency is displayed separately from high/medium/low. Operation approval remains a human responsibility. Real-data normalization and qualified maintenance review are prerequisites for any future production activation.

CSV import and assignment-change history are not inferred from present-day attributes or filenames. An immutable event-to-source relationship is required before those histories can be added.

## Local evidence

The integrated application candidate completed the local Python aggregate with `Ran 2142 tests / OK (skipped=213)`. Class-level skips must not be subtracted from this total to infer a passed-case count. Node tests passed 58 cases; responsive static checks, architecture inventory, generated schema comparison, and whitespace checks passed.

Dedicated PostgreSQL tests and real-browser acceptance remain separate. Passing existing Q08 browser tests alone does not validate the new overview and priority preview interactions. Hosted CI results must be tied to the actual published head SHA.

## Remaining UI acceptance

Verify wide and narrow layouts, all five recommendation links, close/Escape and browser Back/Forward, repeated and interrupted navigation, history filters and pagination, score/evidence separation, preview state retention, read-only preview acquisition, normal form behavior, and default-off/production refusal.

No production deployment or database migration is included in this candidate.
