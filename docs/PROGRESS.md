# Progress

Controlling baseline: MASTER_ROADMAP.md v1.0; phase plan: P2_QUESTION_BANK_PLAN.md. Updated 2 November 2026. Source/API 0.8.0, P2-003. The original roadmap/Word baseline is unchanged.

## Completed

P0/P1 are accepted (P1_ACCEPTANCE.md). P2-001 is accepted for 918036d and its correct CI evidence. P2-002 is accepted: 357 strict local PostgreSQL tests passed, zero skips, 225.30s; 0004 head, clean comparison, restarted API ready and healthy worker status; workflow list screenshot shows successful Foundation gate #3 at e18af0c. No run ID or individual job logs were supplied for that screenshot. See LOCAL_VERIFICATION_P2_001.md and LOCAL_VERIFICATION_P2_002.md.

## Current: P2-003

Implemented immutable exact-version review events, submit/return/approve/retire, independent-review checks against origin/editor/submitter, automatic pending-review supersession during edits, counters/hash fencing, scoped reviewer access and approved public selections. Added database-derived public projection, deferred decision/selection consistency guard, role/trigger readiness checks and atomic review/audit/outbox writes. Existing draft bank read responses now include actual state/review_revision; private drafts and future revisions remain hidden from reviewers until submitted.

Schema head 0005_question_review; eleven forced-RLS tables and five enabled guards. Runtime requires additional limited grants; worker receives no review/selection table access. Prior migrations, dependency locks and question-content.v1 stay unchanged. All previously saved drafts retain their content and start without fabricated decisions/approval.

## Evidence and gate

P2-003 IMPLEMENTED, STRICT LOCAL POSTGRESQL AND NEW REMOTE CI ACCEPTANCE PENDING. Portable gate: 282 tests passed, no skips; dependency/lint/format passed. Full collection: 444 tests (162 PostgreSQL). Offline SQL parser accepted 99 upgrade statements and seven function-definition statements (including earlier definitions/replacement); syntax only. See VALIDATION_P2_003.txt. This workspace cannot execute PostgreSQL under its required non-root server constraints; no database/CI pass is invented.

Next: apply P2_003_UPGRADE_WINDOWS.md, migrate/compare schema, refresh restricted role grants, run all 444 tests without skips, restart/check API and worker, then commit/push and inspect all new CI jobs for the new commit. Once P2-003 passes, record acceptance and begin P2-004 taxonomy/retrieval. Historical CI cannot validate later source.

## Limits

No frontend/browser review journey, taxonomy, protected media, imports, exam publication/scheduling, candidate runner, evaluation/results or adaptive engine yet. Review/selection endpoints are authenticated JSON APIs. Returned content requires a new version to be resubmitted; duplicate commands conflict rather than replay success. Initial create remains without replay idempotency. Point-in-time authority checks do not retroactively cancel already authorized commits. Authoring/review currently serialize per institution; no capacity promise. Privileged owners can disable guards, outside the append-only protection claim. Local receipt worker sends no external messages. Existing Starlette/httpx warning remains tracked. Later production/security/accessibility/recovery gates still apply.
