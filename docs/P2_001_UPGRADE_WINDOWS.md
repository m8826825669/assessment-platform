# Apply P2-001 content-contract increment

The baseline is commit b00e0a8 with a clean working tree and passing P1 gates. This source update adds content contracts/tests and progress/planning records. No new migration, role creation, grant refresh or institution bootstrap is needed. Migration head stays 0003_audit_outbox.

Extract Assessment_Platform_P2_001_v0_6.zip to `D:\school\exam\Assessment\updates\v0_6`, separately from the working repository. Stop the local API/worker while updating source. From PowerShell:

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform"
git status --short
```

If this lists unexpected changes, preserve/review them before applying the bundle. The updater backs up overwritten source, preserves .git/.env/.venv and verifies the three existing migration bytes. It does not automatically commit or push.

```powershell
python "D:\school\exam\Assessment\updates\v0_6\assessment-platform\apply_update.py" --target "D:\school\exam\Assessment\assessment-platform"
if ($LASTEXITCODE -ne 0) { throw "Update failed; stop here" }

git diff --stat
git status --short
Set-Location backend
$env:ASSESSMENT_ALLOW_TEST_DATABASE_CREATION = "1"
.\.venv\Scripts\python.exe ..\scripts\verify.py --local-postgres
if ($LASTEXITCODE -ne 0) { throw "P2-001 verification failed; stop here" }
```

Expected: **299 tests pass, zero skips**, dependency/lint/format checks pass, VERIFICATION=PASS. The existing TestClient warning remains tracked. These tests prove new content contracts plus regression of existing PostgreSQL behavior; they do not prove question-bank persistence, review or media services, which are not implemented yet.

After inspecting the changed/new source and a successful local run:

```powershell
Set-Location ..
git add .gitignore README.md docs backend/app/question_bank backend/tests/test_question_content.py
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw "Staged check failed; stop here" }
git diff --cached --stat
git commit -m "Define P2 question bank plan and validated content contracts"
if ($LASTEXITCODE -ne 0) { throw "Commit failed; stop here" }
git push origin main
if ($LASTEXITCODE -ne 0) { throw "Push failed; stop here" }
git log -1 --oneline
```

Open https://github.com/m8826825669/assessment-platform/actions and inspect Foundation gate for the new commit. All three full Linux PostgreSQL jobs and the partial Windows job must succeed. Share the local verification summary and new CI run/commit evidence. Then record P2-001 acceptance and begin P2-002. Do not reuse the P1 run as acceptance for new content.
