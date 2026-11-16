# Q06 receipt detail recovery

Word v16 §35.3 normal invoice/vehicle-document intake and confirmation.
Base f7e5bed contains #422 and #425 bounded recovery for the upload card and
receipt-list resume. Their fallback destination, the receipt detail page,
still awaited status headers/body without a deadline and reset errors before
processing null JSON. This is the final entry in the same user recovery path.

Two cases failed on the base: repeated 200/null continued polling after three
failures, and a permanently pending body had no deadline. The detail page now
uses the existing local status-GET helper, validates the shape before resetting
errors, and stops after three consecutive failures with explicit reload guidance.

No automatic navigation back to an entry point or reload loop is introduced.
The user checks connectivity/login and reloads the same receipt; no new POST,
upload, OCR retry/cancellation, owner/tenant check, or receipt permission changes.
Existing 401/403/404 failures also stop after three attempts. Normal completion,
preview links and recovery after a transient status failure remain intact.

Local Node controller suite: 19 passed. New cases cover invalid body, body stall,
normal completion, inaccessible status and resetting the transient-failure budget.
No external OCR, production changes, real-device or live business acceptance.
