# Vehicle comparison UI⑤ acceptance

Reference: `05_vehicle_comparison.png` shows the two side-by-side panels, cost/km horizontal bars and the current vehicle's part name, replacement date and distance since replacement. The full 124.9-second video at 87.7 seconds shows the panel headings and top of the table, but clips the complete bars. No example values or vehicle counts from either reference are application defaults.

The projection reuses the existing company/model/registration-year/inactive selector and selected period. The other-vehicle value is the arithmetic mean of each eligible vehicle's registered cost/km, not pooled cost/distance. Existing aggregation keeps unknown values separate from zero, requires matching recorded months, no missing values and positive distance. Completeness of the entire period is not asserted. No new work-status filter is applied to costs. The model's `is_invoice_actual` property also remains a valid actual-replacement basis when work status is not complete. Unconfirmed replacement rows stay visible with a held distance rather than being asserted as completed.

Only an existing usable, dated mileage reference is subtracted from replacement mileage. Missing/non-finite/negative values, same-day conflicting replacement meters, reference conflicts/decreases, future or pre-replacement reference dates, future completion/replacement dates, and unavailable measurement basis are held with a reason. A valid difference of zero is displayed as zero. This does not broaden existing use of maintenance/inspection-only odometer references, infer meter replacement, or change AI/saved source data.

## Tests

`python -m unittest discover -s tests -v` includes `test_vehicle_comparison_panels.py`: pure edge cases and real Flask routes using only temporary synthetic SQLite. A focused run is `PYTHONPATH=.:tests python -m unittest test_vehicle_comparison_panels test_vehicle_analysis_summary -v`.

The dedicated workflow checks out the exact PR head and records its complete commit/tree before running Python Playwright 1.62.0 and Chromium. The browser harness uses authenticated synthetic Flask GET responses, preserving the real CSP headers and actual scripts/styles. No HTTP listener, external DB, external web requests, real login, AI call, deploy, or production setting is used. The isolated runner removes inherited environment settings and uses the existing Python network/SQLite-root guard. Every browser request must be a GET to the fixture origin, with service workers blocked. This is request interception, not a kernel-wide Chromium network isolation claim.

Coverage: 1440/1024/768/390/320 widths; actual numerical values and SVG bar colors/geometry; no inline style/CSP relaxation; long names, large values and 32 part rows; known zero, unknown costs, parts-only and empty states; comparison/period filters, reload, Back and exact existing part-record links; unchanged saved costs/parts; JavaScript-disabled facts, native disclosure and GET forms. Company boundaries, XSS escaping, incomplete samples, invoice-actual work-status mismatch, and mileage edge cases are also checked by route/unit tests.

Local execution (Python must contain application dependencies and Playwright):

```sh
bash tests/vehicle_comparison_browser/run-isolated.sh \
  /absolute/clean/repo /absolute/python /absolute/chromium /absolute/artifacts
```

`DKSS_PLAYWRIGHT_SITE` may point to an already installed official Playwright Python site-packages directory for local execution. It is not needed in CI. The checkout must be clean. Only `browser-result.json` with `status=PASS` and `browser_started=true`, plus exit zero, is browser acceptance. A launch failure does not count as layout verification. Screenshots and logs contain synthetic fixtures only. Real transport/login/MFA, production data, mobile-device rendering and business acceptance remain separate.
