# P2-008 question bank acceptance

Baseline a164343. Requirements QBK-01, QBK-02, TEN-01, PUB-01, SEC-01, ACC-01 and GOV-01.

| Gate | Evidence to retain |
| --- | --- |
| Seven types, taxonomy, independent review and candidate rendering | Full browser gate and owner P2-007 evidence |
| Immutable saved content and exact approved snapshots | PostgreSQL review and media tests, with identical approved-list response bytes after a later edit |
| Retirement and preserved history | Browser verifies the old version badge updates immediately and only that snapshot leaves the approved list |
| Tenant and role isolation, self-review and concurrency | Strict PostgreSQL and browser suites |
| Invalid, foreign-reference and replayed imports | Strict import contract and integration suites |
| Private scan and media access | Strict live storage and scanner suites plus the owner image preview |
| Audit, outbox, schema and readiness | Strict verification report, Alembic checks and API readiness |
| Release evidence | Commit SHA, successful CI run and all job results for that commit |

From the backend directory in the existing Windows setup, with PostgreSQL, private test storage and ClamAV running:

```powershell
$env:ASSESSMENT_ALLOW_TEST_DATABASE_CREATION = "1"
$env:ASSESSMENT_ALLOW_TEST_MEDIA_CREATION = "1"
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe ..\scripts\verify.py --local-postgres
```

From the frontend directory:

```powershell
npm ci
npm run format:check
npm run typecheck
npm test
npm run build
npx playwright install chromium
```

Return to the backend directory in the same PowerShell session and run:

```powershell
.\.venv\Scripts\python.exe ..\scripts\verify_browser.py
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready
```

Stop on a failed check. After the local gates pass, record the results, commit the reviewed changes and check every Foundation gate job on that commit. P2 acceptance requires those results. The historical P2-007 run provides baseline evidence.

This phase covers the governed question bank. Exam assembly, candidate delivery, grading and verification of pinned references in published exams belong to later milestones. See P2_QUESTION_BANK_PLAN.md and FRONTEND_WORKFLOWS.md for media, accessibility and operational limits.

Current result: source changes and regression assertions prepared. Strict backend, frontend and real browser execution and new CI evidence are pending. The workspace lacks the installed test environments and real services. Offline npm installation failed because the cache lacks a pinned dependency.
