# P2-004 upgrade and verification

Baseline: accepted P2-003 commit 5bc13f9 and green Foundation gate #4, with owner strict local verification. API/source becomes 0.9.0 and schema head 0006_question_taxonomy. All five earlier migration files and question-content.v1 remain unchanged. Old saved versions retain their bodies, decisions and selections, with empty classification; no tags are fabricated.

Stop the API and worker. Extract Assessment_Platform_P2_004_v0_9.zip separately to `D:\school\exam\Assessment\updates\v0_9`. Retain your normal local database backup before migrating; the updater's backup covers source only.

From PowerShell:

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform"
git status --short
```

Review unexpected changes before applying the source update. Then:

```powershell
python "D:\school\exam\Assessment\updates\v0_9\assessment-platform\apply_update.py" --target "D:\school\exam\Assessment\assessment-platform"
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
if ($LASTEXITCODE -ne 0) { throw "Runtime grant refresh failed; stop here" }
python -m app.manage grant-worker --role assessment_worker
if ($LASTEXITCODE -ne 0) { throw "Worker grant check failed; stop here" }
$env:ASSESSMENT_ALLOW_TEST_DATABASE_CREATION = "1"
python ..\scripts\verify.py --local-postgres
if ($LASTEXITCODE -ne 0) { throw "P2-004 verification failed; stop here" }
python -m app.worker --status
if ($LASTEXITCODE -ne 0) { throw "Worker status failed; stop here" }
```

Expected: 0006_question_taxonomy (head), clean schema comparison, roles ready, **502 tests passed with zero skips**, VERIFICATION=PASS. Existing TestClient warning remains tracked. No dependency upgrade, password change, role recreation or institution bootstrap is required. Worker refresh never grants question/review/selection/taxonomy data access.

Restart the API using your existing Uvicorn command. In another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready
```

All dependencies should be ok. Worker commands must also run from updated source so the new audit actions are recognized. Share the migration/schema/grant output, strict test summary and readiness/worker results before closing this local gate. Taxonomy/retrieval functionality is exercised in disposable test databases with synthetic users; no new main-database review decisions are created by verification.

After a clean local gate, inspect and commit:

```powershell
Set-Location ..
git diff --stat
git status --short
git add AGENTS.md README.md apply_update.py backend docs
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw "Staged check failed; stop here" }
git diff --cached --stat
git commit -m "Add versioned taxonomy and permission-scoped question retrieval"
if ($LASTEXITCODE -ne 0) { throw "Commit failed; stop here" }
git push origin main
if ($LASTEXITCODE -ne 0) { throw "Push failed; stop here" }
git log -1 --oneline
```

Check https://github.com/m8826825669/assessment-platform/actions for this new commit, not 5bc13f9 or an earlier rerun. All three PostgreSQL/Python jobs and the partial Windows job must pass. Then record P2-004 acceptance and proceed to P2-005 protected accessible media according to BACKLOG.json.

If migration fails, inspect the error/current revision; never stamp head, rewrite an accepted migration or run the API with migration credentials to bypass grants. A source rollback alone does not undo schema. The migration downgrade destroys catalogue/classification history and is for disposable development databases, not automatic rollback of populated institutional data.
