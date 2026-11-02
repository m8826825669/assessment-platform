# P2-002 upgrade and acceptance

Baseline: accepted P2-001 commit 918036d; local 299 tests and CI run 41378575934. This increment adds two question tables, immutable guards/RLS, authoring draft routes and audit events. Existing question-content.v1 and migrations 0001–0003 stay byte-identical. New schema head: 0004_question_versions. API version: 0.7.0.

## Apply source and migrate

Stop the local API and any worker process. Extract Assessment_Platform_P2_002_v0_7.zip to `D:\school\exam\Assessment\updates\v0_7`, separately from the repository. Run from PowerShell:

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform"
git status --short
```

Review any unexpected working changes before applying. The updater preserves .git/.env/.venv, backs up overwritten source, checks existing migrations and never modifies the database. Its backup is a source backup, not a PostgreSQL backup. This is a development migration; retain your normal local database backup before changing schema.

```powershell
python "D:\school\exam\Assessment\updates\v0_7\assessment-platform\apply_update.py" --target "D:\school\exam\Assessment\assessment-platform"
if ($LASTEXITCODE -ne 0) { throw "Source update failed; stop here" }
Set-Location backend
.venv\Scripts\Activate.ps1
python ..\scripts\setup_dev.py
if ($LASTEXITCODE -ne 0) { throw "Setup failed; stop here" }
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Migration failed; stop here" }
python -m alembic current
python -m alembic check
if ($LASTEXITCODE -ne 0) { throw "Schema comparison failed; stop here" }
python -m app.manage grant-runtime --role assessment_runtime
if ($LASTEXITCODE -ne 0) { throw "API grant refresh failed; stop here" }
python -m app.manage grant-worker --role assessment_worker
if ($LASTEXITCODE -ne 0) { throw "Worker grant check failed; stop here" }
$env:ASSESSMENT_ALLOW_TEST_DATABASE_CREATION = "1"
python ..\scripts\verify.py --local-postgres
if ($LASTEXITCODE -ne 0) { throw "P2-002 verification failed; stop here" }
```

Expected: `0004_question_versions (head)`, clean metadata comparison, roles ready, **357 tests passed with zero skips**, VERIFICATION=PASS. The existing TestClient warning is tracked. Tests use random disposable databases/roles, never the main assessment database as their test target. Main migration/grant commands above intentionally update your local assessment schema and role privileges. No role recreation, password change or institution bootstrap is required.

Restart the API with your existing Uvicorn command, then verify `/api/v1/ready` reports all dependencies ok. An old process must not continue against the new schema. Restart bounded worker commands from the updated source too: its validator must recognize the new question audit actions. Worker grants remain separate and do not add access to question tables. A quick operational check remains `python -m app.worker --status`.

## Review and commit after local acceptance

Return to project root and inspect all source changes:

```powershell
Set-Location ..
git diff --stat
git status --short
git add AGENTS.md README.md apply_update.py backend docs
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw "Staged check failed; stop here" }
git diff --cached --stat
git commit -m "Persist tenant-owned questions and immutable version history"
if ($LASTEXITCODE -ne 0) { throw "Commit failed; stop here" }
git push origin main
if ($LASTEXITCODE -ne 0) { throw "Push failed; stop here" }
git log -1 --oneline
```

Check https://github.com/m8826825669/assessment-platform/actions for the new commit, not a rerun of 918036d. All three PostgreSQL/Python jobs and the partial Windows job must pass. Share migration/schema/grant output, the strict verification summary, readiness result, and new commit/CI evidence. Resolve failures before starting P2-003 review/approval.

## Failure handling

A failed transactional Alembic migration should roll back; inspect `alembic current` and the actual error before retrying. Do not stamp head or edit verified migration bytes to hide a failure. If a grant check fails, fix the role configuration rather than using migration credentials for the API. New source fails readiness against the old head or missing grants. Do not automatically downgrade a populated question bank: downgrade drops its tables/history and is for disposable development tests only. Source restoration alone does not roll back schema; review an explicit recovery plan if the upgrade fails after commit.
