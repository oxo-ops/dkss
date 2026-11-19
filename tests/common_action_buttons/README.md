# Approved common action family

Reference: generated 2026-11-18 13:23:47, Library libfile_074701e206fc81919212f7fc6a9ac8d0. User approved “これにして” and “全画面これで統一して”.

- Common family covers existing detail/edit/delete buttons, including master page green/purple overrides. Shallow blue gradient for details/edit, quiet red gradient for delete.
- Existing row-tap and plain navigation are not converted into new buttons.
- CSS deliberately uses important declarations inside a cascade layer to supersede older unlayered important page colors. No visibility, form, permission, CSRF or handler changes.
- 75 static text-labelled action controls reviewed in inventory.json; existing semantic classes also cover Jinja-generated labels. Remaining navigation/cancel links are excluded on purpose.
- Template changes are class-only except the base stylesheet include, validated against #544 with audit.py. Existing production/preview scope is unchanged.
- browser.cjs tests the real stylesheets combined with representative inherited master/table/vehicle contexts at 320/390/700/768/1316px; this is a CSS cascade fixture, not production data or end-to-end deletion testing. Checks touch height, hover colors, hidden/disabled guards, overflow, screenshots.
- Full route/browser operation regression remains necessary before release. Never execute actual deletion for cosmetic QA.
