# P2-006 Windows upgrade and verification

Accepted predecessor: 709e448 (source 0.10.1), 581 strict local tests, all five API dependencies healthy, worker healthy and green Foundation gate #6. New source/API 0.11.0, schema 0008_question_imports. Earlier seven migrations, content.v1 and dependency locks unchanged. Existing question/version/media/review data remains; no old import receipts are fabricated.

## Source update

Stop API/worker processes, keep existing media storage/ClamAV containers running. Retain your normal database backup; updater backup is source only. Extract Assessment_Platform_P2_006_v0_11.zip separately into `D:\school\exam\Assessment\updates\v0_11`.

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform"
git status --short
git log -1 --oneline
```

Review unexpected work before copying. Then:

```powershell
python "D:\school\exam\Assessment\updates\v0_11\assessment-platform\apply_update.py" --target "D:\school\exam\Assessment\assessment-platform"
if ($LASTEXITCODE -ne 0) { throw "Source update failed; stop here" }
Set-Location "D:\school\exam\Assessment\assessment-platform\backend"
.venv\Scripts\Activate.ps1
python ..\scripts\setup_dev.py
if ($LASTEXITCODE -ne 0) { throw "Setup failed; stop here" }
python -m app.media.manage status
if ($LASTEXITCODE -ne 0) { throw "Existing media services are not ready; stop here" }
```

No dependency upgrade, new bucket, storage credential rotation, policy refresh, role recreation or institution bootstrap is needed. The accepted HTTP/1 build adjustment and corrected image/version-read policy are retained. Do not reapply the old media patches or provision another bucket. Do not print .env or credentials.

## Schema and restricted grants

```powershell
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Migration failed; stop here" }
python -m alembic current
python -m alembic check
if ($LASTEXITCODE -ne 0) { throw "Schema comparison failed; stop here" }
python -m app.manage grant-runtime --role assessment_runtime
if ($LASTEXITCODE -ne 0) { throw "Runtime grant refresh failed; stop here" }
python -m app.manage grant-worker --role assessment_worker
if ($LASTEXITCODE -ne 0) { throw "Worker grant check failed; stop here" }
```

Expected 0008_question_imports (head), no new upgrade operations, runtime and worker roles READY. Worker gets no question/import receipt data access. The new private receipt table starts empty; normal import APIs create only complete success receipts.

## Full strict local gate

```powershell
$env:ASSESSMENT_ALLOW_TEST_DATABASE_CREATION = "1"
$env:ASSESSMENT_ALLOW_TEST_MEDIA_CREATION = "1"
python ..\scripts\verify.py --local-postgres
if ($LASTEXITCODE -ne 0) { throw "P2-006 verification failed; stop here" }
python -m app.worker --status
if ($LASTEXITCODE -ne 0) { throw "Worker status failed; stop here" }
```

Expected **652 tests passed, zero skips**, VERIFICATION=PASS; dependency/lint/format checks pass. Existing TestClient warning remains tracked. Tests use random disposable databases/buckets/users, including a live private-media import journey; application institutions/questions/media are not populated or deleted by this verification. Missing PostgreSQL/test-storage/ClamAV or stale scanner definitions must fail rather than skip.

If it fails, share the failure section and stop before committing. Never stamp head, edit an accepted migration, disable scanning or bypass role separation to pass.

## Restart and acceptance

Restart the API with the existing factory command from backend:

```powershell
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-proxy-headers
```

In another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready | ConvertTo-Json -Depth 4
```

Expected status ready and postgresql/schema/runtime_role/media_storage/media_scanner all ok. Share migration/schema/grant output, full test summary and readiness/worker status before closing this local gate.

After a clean local gate, review and commit:

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform"
git diff --stat
git status --short
git add AGENTS.md README.md apply_update.py backend docs
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw "Staged check failed; stop here" }
git diff --cached --stat
git commit -m "Add atomic validated question imports with idempotent receipts"
if ($LASTEXITCODE -ne 0) { throw "Commit failed; stop here" }
git push origin main
if ($LASTEXITCODE -ne 0) { throw "Push failed; stop here" }
git log -1 --oneline
```

Inspect https://github.com/m8826825669/assessment-platform/actions for THIS new commit, not a rerun of 709e448. All three PostgreSQL/Python jobs and the Windows portable job must pass. Record acceptance, then proceed to P2-007 actual browser authoring/review/media/import journeys. P2 overall is still incomplete; no deployment occurs in CI.

A source rollback does not reverse schema. Downgrade destroys import success receipts and their retry guarantees; use only on disposable test databases, never as automatic rollback of an institution's data. No object-storage/scan changes are part of this migration. See QUESTION_IMPORT_API.md for supported profile, limits, key scope, preview and replay semantics.
