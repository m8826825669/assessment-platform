# P1 engineering foundation acceptance

Accepted 2 November 2026 against MASTER_ROADMAP.md v1.0. This closes the engineering foundation, not product completion or production readiness.

## Evidence and provenance

| Gate | Evidence supplied by the owner | Result |
| --- | --- | --- |
| Domain reference | P1-001 original domain checks | 25 tests passed; in-memory only |
| PostgreSQL foundation | LOCAL_VERIFICATION_P1_002.md | 57 tests; migration/schema/readiness accepted |
| Identity and tenancy | LOCAL_VERIFICATION_P1_003.md | 134 tests and real restricted-role authentication/revocation smoke |
| Audit and outbox | LOCAL_VERIFICATION_P1_004.md | 227 strict PostgreSQL tests; real event delivered; repeat had no additional processing |
| Existing Windows environment | Output attached 1 November 2026 | 236 tests, zero skips; full verification passed twice, 176.20 and 175.34 seconds |
| Separate Windows environment | Output attached 2 November 2026; `.venv-p1-005-fresh` | 236 tests, zero skips, 160.02 seconds; dependency, lint and format passed; VERIFICATION=PASS |
| Remote CI | Owner screenshot of run 41375023675, attempt 2, commit b00e0a8 | Success; all four jobs green |

CI run: https://github.com/m8826825669/assessment-platform/actions/runs/41375023675
Repository: https://github.com/m8826825669/assessment-platform
Accepted commit abbreviation, as supplied: `b00e0a8`, branch `main`. A full commit SHA was not supplied and is not invented.

CI job results shown: PostgreSQL 17 / Python 3.11, 3.12 and 3.13; Windows / Python 3.12 (partial). The screenshot establishes job conclusions, not individual test counts or logs. Local test counts above come from the owner's terminal output. Remote API/log access was not used to independently inspect the run. The fresh-environment log starts with requirements already installed in that separate environment; its creation transcript is not included, so acceptance records the separate-environment verification without claiming that particular invocation first created it.

P1-005 and P1 are accepted using the combined evidence. All original migration identities remain unchanged, with current head `0003_audit_outbox`. The existing Starlette/httpx TestClient deprecation warning is tracked and did not fail any gate.

## Limits carried into P2

No frontend or usable assessment journey exists yet. The domain reference is not the persistent delivery engine. The worker consumer writes local receipts and sends no external notifications. Production deployment, capacity, recovery, accessibility and security review remain P6 gates. This record authorizes milestone progression within the existing roadmap, not a production release.
