# Q06 avoid reading the same selected original twice

Word v16 §35.3 requires ordinary invoice/document business consistency and avoids
unnecessary repeated AI work. On main29f03b3, selecting byte-identical PDFs under
two filenames creates two queued drafts, despite the completed-source and upload
key guards. A focused isolated case reproduced this: 2 drafts instead of 1.

The enqueue loop now remembers SHA256 digests only within this single request.
The first occurrence is retained; subsequent identical originals are excluded
before another draft is created. Distinct bytes, even similar filenames or invoice
numbers, remain separate. This is not semantic invoice deduplication or cross-
request/company sharing. Existing file count, pending count and size limits still
apply to the submitted selection; no concurrency or permission rules are relaxed.

The receipt carries repeated_files separately from already-registered ignored_files.
The detail page explains that repeated selections are excluded; it does not claim
those files were already registered. Existing job metadata preserves this notice.

Queue fixtures previously generated many identical PDFs to simulate different
originals. Multi-file workload fixtures now use distinct valid trailing PDF comments.
The legacy-receipt retry test explicitly seeds old duplicate drafts and still
verifies the worker's completed-source safeguard; it has not been removed.

Focused isolated queue suite before the wording correction: 20 passed.
After review, the new mixed-registered case and the affected notice case both passed. It includes same-content renamed copies,
mixed unique/repeated files, the 50-file serial path, accepted upload-key reuse,
size limits, retries, owner boundaries and legacy completed-source skipping.
Tests use temporary SQLite with the existing network/root guard and mocked AI.
No external AI, real company records, production changes or live accuracy claims.

Independent review additionally covered already-registered A, a renamed copy of A,
and new B: only B is queued, with separate registered/repeated notices. The wording
does not promise that registered A is read once, nor that a compound original's
document-type routing can only invoke AI once.
