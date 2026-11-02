# P2-007 owner verification — 2 November 2026

Supplied Windows output: setup passed; schema 0008_question_imports (head), Alembic comparison clean, MEDIA_STORAGE=ok and MEDIA_SCANNER=ok. Strict backend verification: 659 passed, zero skips, one existing TestClient warning, 664.15 seconds, VERIFICATION=PASS. Node v22.22.0. Frontend 0.12.0 typecheck, format, 17 tests and production build passed; Chromium installed.

Browser gate ran against disposable real PostgreSQL/private media/ClamAV and failed: all three scenarios failed, one Python harness failure, 390.34 seconds. First and third timed out locating exact “Import questions”; decorative navigation glyphs participated in the accessible names. Second reached the stale-edit alert after real image/scanning and two-tab editing steps, then failed because the generic alert locator also matched Next's route announcer. Progress through those steps is not acceptance of the complete scenario.

npm ci reported one moderate and one critical vulnerability. Full authoring audit reproduced findings in Vitest 4.0.18 and @vitest/mocker. The earlier production-only audit did not cover development tooling. Targeted frontend correction 0.12.1 pins Vitest 4.1.12; no npm force fix is used.

P2-007 remains unaccepted until corrected frontend audit/checks/build, all three actual browser scenarios, manual checks and new-commit CI pass. No backend source, Python dependency, schema migration or application database/storage correction is needed for this patch.

## Owner 0.12.1 corrected gate

Patch applied; npm ci and npm audit report zero vulnerabilities; Vitest4.1.12: 17 tests pass; format, typecheck and production build pass. Browser: 1 passed / 2 failed; one Python harness failure in 232.61s. Tenant/role scenario passed. Seven-type scenario timed out on exact prompt-label lookup; supplied page snapshot shows a populated saved Version1 editor with no workspace error. Narrow image/conflict scenario failed its final width assertion; captured state still has reload in flight. That screenshot is an accessibility snapshot, not layout geometry, so the exact overflowing element cannot be claimed.

Frontend 0.12.2 separates saved prompt labels, constrains responsive intrinsic sizes and adds geometry diagnostics while retaining the strict no-overflow assertion. All backend bytes and dependency versions remain unchanged. Corrected actual browser and new CI remain pending.

## Owner 0.12.2 gate

Frontend18 tests, typecheck, format and build passed. Real browser seven-type author/review/coordinator/snapshot journey passed in49.4s; tenant/role journey passed in5.2s. Image/conflict journey reached final viewport assertion and failed in8.6s: viewport390, document474, body390, ordinary outside-table offending element list empty. Two scenarios passed, one failed; Python harness failed after79.58s. Thus saved-label correction is proven, but full browser acceptance is not.

Frontend0.12.3 removes absolute hidden table labels in favor of equivalent explicit accessible button names, establishes a local table scroll containing block, and expands width diagnostics to positioned table descendants/shadow roots. Corrected viewport and new CI remain pending.
