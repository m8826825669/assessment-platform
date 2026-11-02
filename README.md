> Current source: 0.9.0 / P2-004 taxonomy and permission-scoped retrieval. Accepted predecessor: 5bc13f9 (P2-003). Follow [P2-004 Windows upgrade](docs/P2_004_UPGRADE_WINDOWS.md), [taxonomy API contract](docs/TAXONOMY_API.md) and [progress](docs/PROGRESS.md). New increment is pending real PostgreSQL and CI acceptance.

# Institutional Assessment Platform

Controlling roadmap: docs/MASTER_ROADMAP.md v1.0. Read AGENTS.md, docs/PROGRESS.md and docs/BACKLOG.json. P2 work follows docs/P2_QUESTION_BANK_PLAN.md.

## Source/API 0.9.0 — taxonomy and retrieval (P2-004)

P1 and P2-001 through P2-003 are accepted with owner-supplied local and CI evidence. This release adds institution subjects/topics/outcomes/tags, fenced catalogue changes and immutable classification snapshots. Scoped question, review and selection collections support literal title/type/state/AND taxonomy filters before bounded pagination. Existing approved content and historical labels stay unchanged after catalogue edits.

Coordinators never need private draft/key/rubric/comment access. The database constructs a separate safe projection and enforces decision/selection atomicity. API/worker roles remain separate; audit/outbox contains allowlisted metadata, not feedback or raw authoring content. No external delivery or frontend is enabled.

## Upgrade

Follow docs/P2_004_UPGRADE_WINDOWS.md. Stop old processes, apply the extracted bundle separately, migrate to 0006_question_taxonomy, compare metadata, refresh existing restricted API grants and verify readiness. Do not recreate roles or bootstrap the institution again.

## Verify

```text
python scripts/setup_dev.py
backend/.venv/bin/python scripts/verify.py --unit-only
```

Windows uses backend\.venv\Scripts\python.exe. Full local acceptance requires configured disposable PostgreSQL test administration and all 502 tests with zero skips, followed by actual CI for the new commit. Portable and SQL parsing checks do not prove database behavior. See docs/DEVELOPER_GUIDE.md.

Review routes and behavior: docs/QUESTION_REVIEW_API.md. Existing draft routes: docs/QUESTION_BANK_API.md; content: docs/QUESTION_CONTENT_CONTRACT.md. P2-003 is accepted on owner evidence. P2-004 remains pending its own local/CI gate. P2 overall is incomplete; media, imports and browser authoring remain planned.
