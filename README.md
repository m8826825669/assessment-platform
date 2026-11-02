# Institutional Assessment Platform

Source/API/UI **0.12.0**, P2-007 institution question-bank browser workflows; pending strict local/browser/new-CI acceptance. P1 and P2-001–P2-006 accepted, latest owner commit 6bae92a. Roadmap v1.0 and final goal unchanged.

Follow [Windows upgrade and verification](docs/P2_007_UPGRADE_WINDOWS.md), [interface journeys](docs/FRONTEND_WORKFLOWS.md), [progress](docs/PROGRESS.md) and [backlog](docs/BACKLOG.json). Read AGENTS.md before changes.

Backend: FastAPI/PostgreSQL, restricted runtime/worker roles, immutable seven-type question versions, independent review, taxonomy, scanned private images and atomic idempotent internal JSON imports. Frontend: Next.js/TypeScript institution workspace, structured editors, history/feedback/review, candidate-safe saved rendering, image controls and import recovery. Schema remains 0008; no migration or Python dependency change.

Local UI: Node 22+, `npm ci` in frontend, existing API at 127.0.0.1:8000, `npm run dev`, visit http://127.0.0.1:3000. Use existing institution accounts; tokens stay in memory and refresh requires login. Never put database/storage secrets in frontend configuration.

Backend portable gate is partial: `python scripts/verify.py --unit-only`. Full gate requires disposable PostgreSQL and dedicated real storage/ClamAV. Frontend checks: `npm run typecheck`, `npm run format:check`, `npm test`, `npm run build`. Separate actual browser gate: backend venv Python `scripts/verify_browser.py`, after installing Chromium as in the Windows guide. Missing services fail rather than skip; no application data is seeded. CI runs frontend/build/browser inside the Python 3.12 PostgreSQL job and performs no deployment.

P2 is incomplete until actual browser and milestone acceptance. No published examination, candidate runner, response upload, scoring engine or production-readiness claim.
