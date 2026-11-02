# P1-004 local acceptance

Evidence supplied by the user on 1 November 2026 from Windows PowerShell and their local PostgreSQL installation. No credentials or payloads are retained.

- Migration: `0003_audit_outbox (head)`; `alembic check`: no new upgrade operations.
- Existing API role grant refresh: `RUNTIME_ROLE=READY`.
- After the 0.4.1 correlation assertion correction, focused PostgreSQL test: 1 passed in 3.41 seconds.
- Full strict PostgreSQL run: **227 passed, no skips**, 1 existing Starlette/httpx deprecation warning, 177.94 seconds.
- Ruff lint passed; Ruff format check: 38 files already formatted.
- Separate worker role provisioning: `WORKER_ROLE=READY`; API and migration settings unchanged.
- Real local producer/worker sequence: pending=1; first worker run processed delivered=1; queue then delivered=1, pending=processing=dead=0.
- Repeated worker run processed nothing; queue remained delivered=1 with all other counts zero.

Conclusion: P1-004 acceptance is complete. This evidence covers the local receipt consumer and the tested API/database behavior; it does not claim external notification delivery or production operation. Continue to P1-005, then review the whole P1 gate before entering P2.
