# Institutional Assessment Platform

The controlling plan is docs/MASTER_ROADMAP.md. Read AGENTS.md, docs/PROGRESS.md and docs/BACKLOG.json before changes. The original Word roadmap remains the v1.0 baseline.

## Source release 0.5

P1-004 passed on the user's Windows/PostgreSQL installation: all 227 tests, migration/schema checks, lint/format, separate worker provisioning, delivery of a real event and repeat processing without another effect. See docs/LOCAL_VERIFICATION_P1_004.md.

P1-005 adds a repeatable environment setup, dependency consistency checks, one strict verification command and GitHub Actions jobs. No application/schema behavior changes; database head remains 0003_audit_outbox. API package version remains 0.4.0 because this is a tooling release.

## Existing installation

Follow docs/P1_005_UPGRADE_WINDOWS.md. Apply the archive separately using apply_update.py, which checks all three existing migration files and preserves .env/.venv. No new migration, role creation or institution bootstrap is needed.

## Developer entry points

```text
python scripts/setup_dev.py
backend/.venv/bin/python scripts/verify.py --unit-only
```

On Windows use backend\.venv\Scripts\python.exe. Full acceptance requires the same verification command without --unit-only and configured disposable PostgreSQL test administration. For the existing local Windows installation, use --local-postgres as documented. Partial passes never close the gate.

See docs/DEVELOPER_GUIDE.md for fresh setup, lockfiles, CI, test isolation and the P1 review checklist. The workflow expects this project at repository root. No repository was created or remote CI executed in this release.

## Current scope

Identity, tenant access, audit/outbox and the local worker receipt consumer are implemented. No frontend, persisted question bank, exam runner, scoring or results workflow is delivered yet. The domain kernel is still an in-memory reference. Worker processing sends no external messages. See docs/AUDIT_OUTBOX_CONTRACT.md and docs/IDENTITY_API.md.

P1 remains open pending fresh local PostgreSQL verification and real CI evidence. Review the whole P1 gate before beginning P2.
