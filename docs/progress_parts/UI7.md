Step: Phase 7 UI package (branch p7-ui).
Done: api/ai.ts; screens in frontend/src/ai (queue, documents, extraction, narration, mappings, Tally import / export, AI settings); nav group "Documents & AI" and 8 routes (append-only).
Tests: vitest 126 passed (ai/lib.test.ts adds 12); `npm run build` clean.
Commit: see git log of p7-ui.
Decisions added: docs/decisions_parts/UI7.md (7 rows); queue and narration endpoints unverified against package F.
