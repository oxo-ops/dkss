# Optional certificate deadline evidence

This provider connects the approved high-60 floor only for the arrival/passing of a **confirmed applicable vehicle inspection certificate expiry date**. It does not decide driving permission or whether a certificate has expired at a particular hour. It does not generalize to periodic inspection deadlines.

## Sources and explicit confirmation

The normal analysis detail screen offers saved, linked certificate originals. The server rereads the same company/vehicle, original SHA-256, literal expiry next to the same chassis/model on the PDF page, current registered expiry, vehicle facts, and registered inspection/execution/evidence history. Both inline and existing company-scoped compacted originals work. Extraction output alone is not evidence. Image-only/ambiguous originals and documents explicitly marked as fictional/sample cannot qualify.

The server does not choose the largest date or newest upload. Different original dates require a connected previous-expiry → new-expiry execution chain. A changed registration alone, unmatched update, unresolved legacy inspection kind, unlinked vehicle-inspection original record, or competing same-day update prevents confirmation. A confirmed periodic 12-month inspection never becomes a certificate deadline.

The optional authenticated confirmation has four separate statements:

1. This is the actual vehicle's official certificate or certificate record; for an electronic certificate, its current electronic expiry record agrees.
2. Later inspections, updates and corrections, including items not yet registered, were checked and the selected original is current.
3. The vehicle category/use is within the certificate-validity rule's scope.
4. Current notices, extensions and exceptions were checked for the vehicle's principal place of use and target date; the displayed original date applies unchanged.

Unknown applicability or an applicable extension is unsupported by this initial provider. It accepts no hand-entered effective date and never infers the absence of an extension from missing data. The preview includes original text, download link, registered update relations, supported scope, date and official explanatory reference.

## Date, change and cancellation behavior

The confirmation applies to the **Japan calendar day on which the human checked applicability**. This is the evidence's scope, not a new scoring rule or daily mandatory task. The server includes that day, source versions, update history and fixed statements in the fingerprint. On another day or after changed evidence, the common workflow holds the confirmation rather than silently accepting a new legal-applicability claim. Existing unrelated findings and saved analysis JSON remain unchanged. Missing or held evidence is never a new low/zero assessment.

Before expiry arrives, the adapter returns `skip_assessment=True` and no timing. On the expiry calendar day or later, a valid current confirmation supplies `TimingFact(legal_deadline=True)` to the unchanged core. Cancellation is distinct: the common workflow retains the audit and suppresses only proposals bound to that withdrawn confirmation. Correction adds cancellation and a new confirmation in one transaction.

## Interface

Module: `dkss_app.priority_certificate_sources`.

- `certificate_confirmation_options(vehicle, *, as_of=None)` supplies optional fields and missing conditions.
- `preview_certificate_confirmation(vehicle, selection, *, as_of=None)` requires only the selected `document_id` and returns canonical sources, fingerprint, display sources and four statements.
- `certificate_confirmation_inputs(preview, *, event_id, confirmed_on, as_of=None)` is called only after the common active-confirmation reader verifies actor, audit, all statements, current source fingerprint and absence of cancellation. It returns core scope/evidence/references/timings, never a driving decision.
- `read_certificate_confirmation_original(vehicle, document_id, *, as_of=None)` supplies verified bytes/filename/MIME to the authenticated company/vehicle-scoped download route.

## Official scope references

- MLIT, statute collection updated 2026-06-01, Road Transport Vehicle Act articles 58, 61-2 and 62: <https://www.mlit.go.jp/jidosha/content/001740686.pdf>. Article 61-2 permits published extensions based on principal place of use; a printed date alone therefore cannot settle applicability.
- Electronic certificate guidance: <https://denshishakensho-portal.mlit.go.jp/user/>. A card face alone is not accepted as evidence of an absent expiry value.

The built-in reference is explanatory and versioned. It is not a comprehensive, continuously updated list of current extension notices, nor an automatic legal opinion. Operational expert review remains separate from this implementation/verification.

## Focused verification

`tests/test_priority_certificate_sources.py` uses only newly created disposable SQLite databases, fictional vehicle values and actual synthetic PDF bytes. It covers core arrival/past/future behavior, original/extraction/checksum/scope conflicts, update chains, separate periodic kinds, compacted storage boundaries, optional normal HTTP preview/save/active/download/cancel/correct, incomplete statements, changed sources, replay, foreign company/nonprivileged users, replaced or locked actor identities, next-day hold and read-only/size limits. No live originals, real identifiers, AI/network request or production database is used. Full aggregate/browser validation belongs to the final integration candidate.
