# P2-003 upgrade and verification

Baseline: accepted P2-002 commit e18af0c, 357 local tests and successful Foundation gate. API/source becomes 0.8.0 and schema head 0005_question_review. All four earlier migration files and question-content.v1 remain unchanged. New decisions and selection projections start empty; no old drafts are approved automatically.

Stop the API and worker. Extract Assessment_Platform_P2_003_v0_8.zip separately to `D:\school\exam\Assessment\updates\v0_8`. Retain your normal local database backup before migrating; the updater's backup covers source only.

From PowerShell:

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform"
git status --short
```

Review unexpected changes before applying the source update. Then:

```powershell
python "D:\school\exam\Assessment\updates\v0_8\assessment-platform\apply_update.py" --target "D:\school\exam\Assessment\assessment-platform"
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
if ($LASTEXITCODE -ne 0) { throw "P2-003 verification failed; stop here" }
python -m app.worker --status
if ($LASTEXITCODE -ne 0) { throw "Worker status failed; stop here" }
```

Expected: 0005_question_review (head), clean schema comparison, roles ready, **444 tests passed with zero skips**, VERIFICATION=PASS. Existing TestClient warning remains tracked. No dependency upgrade, password change, role recreation or institution bootstrap is required. Worker refresh never grants question/review/selection data access.

Restart the API using your existing Uvicorn command. In another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready
```

All dependencies should be ok. Worker commands must also run from updated source so the new audit actions are recognized. Share the migration/schema/grant output, strict test summary and readiness/worker results before closing this local gate. Review functionality is exercised in disposable test databases with synthetic users; no new main-database review decisions are created by verification.

After a clean local gate, inspect and commit:

```powershell
Set-Location ..
git diff --stat
git status --short
git add AGENTS.md README.md apply_update.py backend docs
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw "Staged check failed; stop here" }
git diff --cached --stat
git commit -m "Add independent question review and approved selection"
if ($LASTEXITCODE -ne 0) { throw "Commit failed; stop here" }
git push origin main
if ($LASTEXITCODE -ne 0) { throw "Push failed; stop here" }
git log -1 --oneline
```

Check https://github.com/m8826825669/assessment-platform/actions for this new commit, not e18af0c or an earlier rerun. All three PostgreSQL/Python jobs and the partial Windows job must pass. Then record P2-003 acceptance and proceed to P2-004 taxonomy/retrieval according to BACKLOG.json.

If migration fails, inspect the error/current revision; never stamp head, rewrite an accepted migration or run the API with migration credentials to bypass grants. A source rollback alone does not undo schema. The migration downgrade destroys review/selection history and is for disposable development databases, not automatic rollback of populated institutional data.
