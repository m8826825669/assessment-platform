# Institutional Assessment Platform

Controlling roadmap: docs/MASTER_ROADMAP.md v1.0. Read AGENTS.md, docs/PROGRESS.md and docs/BACKLOG.json before changes. P2 task/acceptance plan: docs/P2_QUESTION_BANK_PLAN.md.

## Source/API 0.7.0 — persistent saved drafts (P2-002)

P1 is accepted and P2-001 passed the owner's strict 299-test PostgreSQL gate and all four CI jobs for commit 918036d. This increment adds persistent question identities, immutable content/title versions, revision conflicts, author/admin boundaries and atomic audit/outbox records. Candidate-safe JSON preview is staff-only. Review/approval and the frontend remain future P2 work.

## Upgrade

Follow docs/P2_002_UPGRADE_WINDOWS.md. Apply the extracted bundle separately; stop old API/worker processes, migrate to 0004_question_versions, compare schema and refresh the existing restricted API role. Keep migration/API/worker credentials separate. No role recreation or institution bootstrap. No dependency upgrades.

## Verification

```text
python scripts/setup_dev.py
backend/.venv/bin/python scripts/verify.py --unit-only
```

Windows uses backend\.venv\Scripts\python.exe. Full acceptance requires disposable PostgreSQL test administration and all 357 tests with zero skips. Existing Windows installations can use --local-postgres as documented. Portable tests and SQL parsing do not prove database behavior.

See docs/QUESTION_BANK_API.md for routes, ownership, snapshots, retry semantics and audit privacy. Content contracts remain documented in docs/QUESTION_CONTENT_CONTRACT.md. All seven question types are retained. P2-002 is implemented pending actual local PostgreSQL and new remote CI evidence; P2 overall is incomplete.
