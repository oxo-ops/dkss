# Focused offline validation

Result: 54 synthetic stdlib tests passed in `tests.log`. Tests run only the new ledger functions/CLI and bundled pure projector against synthetic input and new private temporary state, with an empty inherited environment. No product/app tests or production integrations ran.

Independent review found two medium issues in the initial artifact:

1. A FIFO at the state path could block before regular-file validation. Fixed by nonblocking open followed by `fstat`; regression confirms prompt rejection and writer-lock cleanup.
2. A known marker plus an unknown failure marker could lose the unknown-marker review signal. Fixed by independent unknown-marker detection, a fixed boolean retained alongside the known classification, review-required status, and cross-run conflict retention. Original unknown marker text is never stored.

Additional regressions cover post-replacement directory-fsync failure, safe uncertainty/replay, unknown nested state, and preservation of `uncertain` notification state when a new conflicting classification arrives.

Independent final recheck verified both implementation/test hashes below and confirmed both findings fixed, with no remaining concrete issue in that narrow recheck. It did not run product/app or external integration tests.

Fixed implementation hashes:

- `log_ledger.py`: `23c728f96af101275d9c714346a8a5e34f1505d5f92c9a8209de63d8dddc03b8`
- `test_log_ledger.py`: `fe2dbd704ce942b9b988c1d5b5aeedd39f27db885e937246a5178122efa47e64`
- Unchanged `log_event_receipts.py`: `f27d2a5647d1d1707e51ad2a06209d4ce7ebff315f34fe74ecbdcbc4be4732a7`

Remaining boundaries are intentional: offline trusted-input recording only; timestamp-only chains are observed progress, not missing-free coverage; `read_checkpoint` always remains null; no scheduler, live collection, delivery, retry, or human acknowledgment. The state is owner-private and bounded, not an operational retention store or a cryptographic audit system.

## Repository preservation checks

All seven files in the original manifest were checksum-verified before copying.
The 54 tests were rerun successfully with an empty inherited environment. The
implementation, projector, tests, fixture, and original focused test log remain
byte-identical. README additions and this validation note describe preservation;
`SHA256SUMS` now covers these updated documents and `INTEGRATION.md`.

The repository base was verified through the official GitHub API as main commit
`e8a529e48be239e1acbebbab333fe6395fd061f3`, tree
`1463cb2ae034d9847cfe090f1435a6be4d48eabd`. Its recursive tree was not truncated
and contained no AGENTS.md or .agents skills. The runtime operations guide and
all existing workflow triggers were inspected. No existing file is replaced.
The added workflow runs only synthetic tests on the exact PR head; production
workflows, application files, dependencies, and service configuration are untouched.
The dedicated remote CI result remains a separate per-commit observation.
