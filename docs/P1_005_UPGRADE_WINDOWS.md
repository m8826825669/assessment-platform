# P1-005 update and verification

This increment adds developer tooling and CI. Schema head remains `0003_audit_outbox`; no new database migration, role creation, grant refresh or bootstrap is required.

## Apply to the existing project

Stop the API and worker while updating source. Extract the archive to `D:\school\exam\Assessment\updates\v0_5`, separately from your working project. The extracted folder must contain `assessment-platform\apply_update.py`.

From PowerShell:

```powershell
python "D:\school\exam\Assessment\updates\v0_5\assessment-platform\apply_update.py" --target "D:\school\exam\Assessment\assessment-platform"
if ($LASTEXITCODE -ne 0) { throw "Update failed; stop here" }
Set-Location "D:\school\exam\Assessment\assessment-platform\backend"
.venv\Scripts\Activate.ps1
python ..\scripts\setup_dev.py
if ($LASTEXITCODE -ne 0) { throw "Setup failed; stop here" }
$env:ASSESSMENT_ALLOW_TEST_DATABASE_CREATION = "1"
python ..\scripts\verify.py --local-postgres
if ($LASTEXITCODE -ne 0) { throw "Verification failed; stop here" }
```

The updater verifies all three existing migrations and preserves `.env` and `.venv`. Setup reuses the default backend environment and installs the pinned development dependencies. Verification uses your configured migration connection only as the administrator connection for random disposable test databases. It does not migrate, seed or drop your `assessment` database. Test administration requires CREATEDB, CREATEROLE and ownership/grant authority in the created databases. Never run this against a shared production PostgreSQL server.

Expected: lint and format pass, **236 tests pass, zero skips**, and `VERIFICATION=PASS`. The existing TestClient deprecation warning remains recorded. The sanitized result is at `assessment-platform\artifacts\verification.json`; it contains counts and stage status, not credentials.

## Prove a fresh dependency setup separately

Do this after the first gate passes. The additional environment is disposable and does not replace your working `.venv`.

```powershell
python ..\scripts\setup_dev.py --venv .venv-p1-005-fresh
if ($LASTEXITCODE -ne 0) { throw "Fresh setup failed; stop here" }
.\.venv-p1-005-fresh\Scripts\python.exe ..\scripts\verify.py --local-postgres
if ($LASTEXITCODE -ne 0) { throw "Fresh environment gate failed; stop here" }
```

## CI acceptance

The archive includes `.github/workflows/ci.yml` at the project root. It will run when this complete project is placed at the root of a GitHub repository and pushed, on a pull request, or via manual dispatch. No repository was created or published for you. See DEVELOPER_GUIDE.md for the job matrix and gate requirements.

P1-005 and P1 overall remain pending until fresh local PostgreSQL verification and the actual remote CI jobs pass. Keep the roadmap unchanged and do not enter P2 yet.
