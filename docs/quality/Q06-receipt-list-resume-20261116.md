# Q06 receipt-list resume after communication failure

Word v16 §35.3: the normal invoice/vehicle-document workflow includes returning
to an already accepted receipt. This entry is distinct from new-upload HTTP202
progress fixed by #422.

## Reproduction and scope

On base b17759d, a 200/null status body resets the error counter before accessing
job.files. Each retry then throws, keeping the counter at one forever. A fetch
or body that never settles never reaches the existing three-error fallback.
The read control and loading indicator therefore remain busy.

Two new Node cases failed against that base, independently of actual OCR or
network access. They now pass with the original 14 controller cases (16 total).

## Change

Reuse the reviewed #422 status-read deadline implementation in a shared local
helper; keep new-upload behavior unchanged. Receipt-list resume now covers both
headers and body with a 20-second deadline and validates the status shape before
resetting errors. After three consecutive failures, the existing fallback opens
the original receipt and restores controls. A timeout aborts only a status GET;
it does not create, cancel, or retry a durable OCR job or upload.

The owner/tenant server checks and same-origin URL checks remain unchanged.
Normal completion still presents its existing result link. No production data,
external OCR, real browser/device acceptance, or deployment is claimed.
