# Q06: recover an accepted receipt when status polling fails

Quality plan Word v16 section 35.3 prioritizes normal invoice/document intake and confirmation. Based on main 18c7364291b9bc92dbcc8f6fbdaf20b131b304e1.

## Reproduced problem

After the upload returns 202, the upload card polls status. Its catch path previously retried indefinitely while leaving controls disabled and providing no receipt link. A lost session, missing/inaccessible receipt, repeated 503, invalid JSON/login HTML or network outage could leave an operator waiting without a recovery action. Isolated JS tests failed against the original code for unbounded polling and absent recovery.

The separate existing-receipt resume path already limits failures to three; this change brings new-upload polling into line without altering that path.

## Limited change

- 401/403 stop polling and ask the operator to check their login, then open the original receipt.
- 404 stops polling and asks the operator to check the company/user and receipt list. `own_batch` deliberately returns 404 for both insufficient authority and unavailable batches. Do not claim a failed upload or reveal another owner's existence.
- Transient network/server/JSON failures retain two automatic status retries. Three consecutive failures stop status polling and provide the original same-origin receipt link. A successful response resets the failure count.
- Stop the spinner, but retain the accepted-upload submission guard and disabled upload controls. Do not POST again, discard the receipt key, retry OCR, alter permissions or fabricate an OCR result. Opening the receipt uses its unchanged server-side ownership checks and may start the existing durable worker according to normal server behavior.
- Healthy status progression and preview redirect are unchanged. This does not cancel the server's accepted job.

## Verification and limits

12 Node isolated controller tests passed (8 existing, 4 new), no network/AI/DB access; diff check passed. New coverage: 401/403/404, bounded transient failures, recovery resetting failures, 503 and non-JSON responses, same-origin receipt link, spinner stopped, and duplicate upload blocked. No real browser/device, production outage, login, external OCR or production-data acceptance is claimed. Independent review pending; no production changes.

## Independent-review follow-up

- A 200 response is not automatically a valid status: null, arrays, missing
  counters/state, or null file entries consume the same consecutive-failure budget.
  Reset that budget only after successful processing, not immediately after JSON parsing.
- Each status GET, including its JSON body read, has a 20-second deadline.
  Timeout aborts only the status GET, never the durable OCR job or upload.
  After three consecutive failures, the operator can open the original receipt
  after connectivity recovers; no automatic upload or OCR resubmission occurs.
- Node suite: 14 passed, including permanently pending headers and body, malformed
  successful JSON, unchanged normal preview completion and duplicate-upload guard.
