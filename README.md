# Institutional Assessment Platform

MASTER_ROADMAP.md in docs remains the controlling v1.0 plan. Read AGENTS.md, docs/PROGRESS.md and docs/BACKLOG.json before changes.

## Source release 0.6 — P2-001

P1 engineering foundation is accepted: local and separate-environment 236-test PostgreSQL gates, and all four remote CI jobs for b00e0a8. See docs/P1_ACCEPTANCE.md for provenance and limits.

P2 is now expanded into eight tasks in docs/P2_QUESTION_BANK_PLAN.md. This first increment implements seven content-validation contracts, immutable nested values, safe candidate-preview projection and full-content fingerprints. Examples and JSON Schema are included. Persistence, review, taxonomy, media, imports and browser journeys remain upcoming P2 tasks. No new question-bank API, grading engine or frontend is claimed.

## Upgrade and verify

Follow docs/P2_001_UPGRADE_WINDOWS.md. Existing schema remains 0003_audit_outbox; no new migration/role/bootstrap is needed. API package version remains 0.4.0 because existing endpoints are unchanged.

```text
python scripts/setup_dev.py
backend/.venv/bin/python scripts/verify.py --unit-only
```

Windows uses backend\.venv\Scripts\python.exe. Full mode requires disposable PostgreSQL test administration; --local-postgres privately loads existing migration settings. See docs/DEVELOPER_GUIDE.md.

Current source needs its own strict local and remote CI acceptance before P2-002. Candidate preview projection is a content helper, not an authorization boundary. See docs/QUESTION_CONTENT_CONTRACT.md.
