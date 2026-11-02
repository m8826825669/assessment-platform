# Institutional Assessment Platform

Controlling roadmap: docs/MASTER_ROADMAP.md v1.0. Read AGENTS.md, docs/PROGRESS.md and docs/BACKLOG.json. P2 work follows docs/P2_QUESTION_BANK_PLAN.md.

## Source/API 0.8.0 — independent review (P2-003)

P1, P2-001 and P2-002 are accepted with owner-supplied local and CI evidence. This release adds immutable review decisions, independent submit/return/approve/retire actions, exact-version fencing, pending-review supersession during edits and approved public selection for coordinators. Existing approved content stays immutable and can be retired from future selection.

Coordinators never need private draft/key/rubric/comment access. The database constructs a separate safe projection and enforces decision/selection atomicity. API/worker roles remain separate; audit/outbox contains allowlisted metadata, not feedback or raw authoring content. No external delivery or frontend is enabled.

## Upgrade

Follow docs/P2_003_UPGRADE_WINDOWS.md. Stop old processes, apply the extracted bundle separately, migrate to 0005_question_review, compare metadata, refresh existing restricted API grants and verify readiness. Do not recreate roles or bootstrap the institution again.

## Verify

```text
python scripts/setup_dev.py
backend/.venv/bin/python scripts/verify.py --unit-only
```

Windows uses backend\.venv\Scripts\python.exe. Full local acceptance requires configured disposable PostgreSQL test administration and all 444 tests with zero skips, followed by actual CI for the new commit. Portable and SQL parsing checks do not prove database behavior. See docs/DEVELOPER_GUIDE.md.

Review routes and behavior: docs/QUESTION_REVIEW_API.md. Existing draft routes: docs/QUESTION_BANK_API.md; content: docs/QUESTION_CONTENT_CONTRACT.md. P2-003 remains pending its local/CI gate. P2 overall is incomplete; taxonomy, media, imports and browser authoring remain planned.
