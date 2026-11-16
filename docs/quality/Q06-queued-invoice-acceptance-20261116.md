# Q06: durable invoice queue to confirmed business records

## Evidence scope

Reviewed against main `07f07203bf7e20beb6248b4fa8ff0f7f05cc3441` and quality-plan Word v15 sections 31.5 / 34.1. The remaining real OCR-to-review-to-application acceptance is not complete merely because #396 numerical normalization shipped.

Existing `test_document_import_queue.py` exercises queued inspection documents. Existing `test_document_connections.py` exercises invoice-to-inspection, costs, parts, history and retained sources through the legacy synchronous upload. The added test connects the **normal durable invoice queue** to the latter assertions, rather than repeating the already-accepted numerical bounds tests or restarting #352.

## Added contract

- The invoice HTTP receipt persists before extraction; extraction in that HTTP call fails the test.
- The actual durable worker classifies/extracts one synthetic maintenance invoice exactly once; a second worker poll finds no job.
- Status and preview are readable, but no maintenance cost record or part replacement exists before confirmation.
- A real confirmation request links the invoice to the selected inspection, creates the expected cost and part records, and exposes source/history/cost/parts views.
- A repeated confirmation is rejected and cannot double the record counts.
- Existing synchronous-path assertions remain shared and unchanged.

Only the classifier and OCR provider are mocked. Fixtures use temporary SQLite, synthetic PDF/data, disabled outbound integrations and the existing Python network/SQLite-root guard. No production configuration, records, deployment, merge, paid OCR call or user authentication was changed.

## Verification

2026-11-16: `DocumentConnectionTests`: **7 passed**, including the new durable invoice connection. Existing six tests remain included. `git diff --check` passed. This is focused isolated integration coverage, not full regression, PostgreSQL concurrency proof, live OCR accuracy, actual login/MFA, browser/device acceptance, or production acceptance. Those remaining checks must not be marked completed by this result.
