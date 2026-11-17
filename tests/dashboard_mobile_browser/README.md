# Mobile dashboard candidate acceptance

Run only in disposable fixtures. The shell wrapper empties inherited environment;
Python audit guard denies external sockets/DBs, browser requests are routed only
to fixture GET responses. Buttons are click-tested without submitting POSTs.

```
DKSS_BROWSER_ARTIFACT_DIR=/absolute/output bash tests/dashboard_mobile_browser/run-isolated.sh \
  /absolute/repository /absolute/python --expected-sha EXACT_HEAD --preflight-only
DKSS_BROWSER_ARTIFACT_DIR=/absolute/output bash tests/dashboard_mobile_browser/run-isolated.sh \
  /absolute/repository /absolute/python --expected-sha EXACT_HEAD --run-browser --chromium /absolute/chromium
```

Checks: real index/base template, fixture safety records, 320/390/600/601/768/1316 widths,
driver/admin, exact full notice text reachability, role/checklist/exit hit targets,
notification open/close, native remaining-items keyboard expand/collapse, link
height and horizontal bounds, 200% computed-font simulation on 320/390 short viewports,
JS-disabled full text and direct record navigation/Back. Screen captures for visual judgment required.

No data truncation, no role/CSRF changes. Existing dashboard safety, saved
proposal and demo workflow tests remain separate. This unexecuted browser script does not prove iPhone/WebKit or actual browser
text enlargement. Empty/1/3/many item geometry is not covered by its fixed four-record fixture. Mobile screenshots are NOT yet passed locally:
Chromium startup is blocked by socket permission, including escalated retry.
Before publication: rebase onto final manual+OCR release, run exact-head CI and
review actual screenshots. c35-compatible isolated candidate is not ready for
Live based on unit tests alone.

Video alignment: actual frames of the current 93-second introduction (v6) and
full-length introduction (v5) show pale-blue headers, white rows, short titles,
secondary context and a right-edge detail cue. They are illustrative PC screens,
not an actual mobile driver home. This candidate preserves real metadata rather
than copying fictional counts. The fixture now includes six saved synthetic AI
proposals (five previewed and one expandable) and an empty other-vehicle group;
proposal screenshots and link bounds are checked too. No AI generation occurs.
