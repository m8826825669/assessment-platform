# P2-007 Windows upgrade and acceptance

Accepted predecessor: 6bae92a / source 0.11.0 / schema 0008. New source/API/UI: 0.12.0. No migration, new database grant, media policy refresh or Python dependency change. All eight accepted migrations stay unchanged. Keep storage/scanner containers running. Extract the new ZIP outside your repository under D:\school\exam\Assessment\updates\v0_12.

Stop API/worker processes before source update. In PowerShell:

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform"
git status --short
git log -1 --oneline
python "D:\school\exam\Assessment\updates\v0_12\assessment-platform\apply_update.py" --target "D:\school\exam\Assessment\assessment-platform"
if ($LASTEXITCODE -ne 0) { throw "Source update failed; stop here" }
Set-Location backend
.venv\Scripts\Activate.ps1
python ..\scripts\setup_dev.py
if ($LASTEXITCODE -ne 0) { throw "Setup failed; stop here" }
python -m alembic current
python -m alembic check
if ($LASTEXITCODE -ne 0) { throw "Schema check failed; stop here" }
python -m app.media.manage status
if ($LASTEXITCODE -ne 0) { throw "Media services unavailable; stop here" }
$env:ASSESSMENT_ALLOW_TEST_DATABASE_CREATION = "1"
$env:ASSESSMENT_ALLOW_TEST_MEDIA_CREATION = "1"
python ..\scripts\verify.py --local-postgres
if ($LASTEXITCODE -ne 0) { throw "P2-007 backend gate failed; stop here" }
```

Expected unchanged 0008_question_imports (head), clean schema, both media dependencies ok; **659 tests pass without skips**, VERIFICATION=PASS. Existing TestClient warning is tracked.

Install frontend dependencies and Chromium (Node 22+ required; do not update unrelated projects):

```powershell
Set-Location ..\frontend
node --version
npm ci
if ($LASTEXITCODE -ne 0) { throw "Frontend install failed; stop here" }
npm run typecheck
if ($LASTEXITCODE -ne 0) { throw "Type check failed; stop here" }
npm run format:check
if ($LASTEXITCODE -ne 0) { throw "Frontend format failed; stop here" }
npm test
if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed; stop here" }
npm run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed; stop here" }
npx playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Chromium installation failed; stop here" }
Set-Location ..\backend
python ..\scripts\verify_browser.py
if ($LASTEXITCODE -ne 0) { throw "Real browser gate failed; stop here" }
```

Expected 17 frontend tests pass, production build succeeds, then **three Playwright scenarios pass**, one Python harness test passes, BROWSER_GATE=PASS. The separate browser gate uses only random disposable PostgreSQL/media fixtures and synthetic accounts; application institution data is not seeded. Keep port 14173 free. A missing browser, storage or scanner must fail. Share failure output before modifying code; never disable isolation/scanning to pass.

Start normal API in backend:

```powershell
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Start UI in a second terminal:

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform\frontend"
npm run dev
```

Open http://127.0.0.1:3000 and sign in using your actual institution admin account. Check the bank and empty state, keyboard navigation, seven-type controls, save/preview/feedback, media status/alt text, and import errors. Use synthetic questions only. Independent approval needs a different authorized reviewer; never approve as the author. If no reviewer exists, use the disposable automated journey for that gate rather than creating real accounts casually. Also verify the visible reason/return/retire actions and manual narrow-screen readability. Record observations/limitations; automated focus checks do not establish WCAG conformance.

From another terminal:

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform\backend"
.venv\Scripts\Activate.ps1
python -m app.worker --status
if ($LASTEXITCODE -ne 0) { throw "Worker status failed; stop here" }
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready | ConvertTo-Json -Depth 4
```

Expected all five dependencies ok; dead/pending/processing zero or understood real pending activity. Share backend/frontend/browser summaries and screenshots before local acceptance.

After the local gate is clean:

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform"
git diff --stat
git status --short
git add .github/workflows/ci.yml .gitignore AGENTS.md README.md apply_update.py backend docs frontend scripts/verify_browser.py
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw "Staged check failed; stop here" }
git diff --cached --stat
git commit -m "Add governed question bank browser workflows and live journey gate"
if ($LASTEXITCODE -ne 0) { throw "Commit failed; stop here" }
git push origin main
if ($LASTEXITCODE -ne 0) { throw "Push failed; stop here" }
git log -1 --oneline
```

Check the new commit's Foundation gate, including the frontend/build/browser steps inside PostgreSQL/Python 3.12. A rerun of 6bae92a is not P2-007 evidence. All four jobs must pass. Record acceptance before P2-008. No production deployment is part of this update.
