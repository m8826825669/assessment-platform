# P2-007 correction 0.12.1 — Windows

Your full backend gate passed: 659 tests, schema clean and both media services healthy. Preserve that result. This patch changes only frontend accessible names, browser selectors and the exact Vitest development dependency/lock, plus evidence documentation. API/backend remains 0.12.0 and schema remains 0008. No migration, grant, storage-policy or account change.

Extract Assessment_P2_007_Fix_v0_12_1.zip outside the repository under D:\school\exam\Assessment\updates\v0_12_1. Stop a running frontend dev server before applying; keep storage/ClamAV running. Use your existing backend virtual environment:

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform\backend"
.venv\Scripts\Activate.ps1
python "D:\school\exam\Assessment\updates\v0_12_1\assessment-p2-007-fix-0.12.1\apply_p2_007_fixes.py" --target "D:\school\exam\Assessment\assessment-platform"
if ($LASTEXITCODE -ne 0) { throw "P2-007 correction failed; stop here" }
Set-Location ..\frontend
npm ci
if ($LASTEXITCODE -ne 0) { throw "Frontend install failed; stop here" }
npm audit
if ($LASTEXITCODE -ne 0) { throw "Dependency audit needs review; stop here" }
npm run format:check
if ($LASTEXITCODE -ne 0) { throw "Format failed; stop here" }
npm run typecheck
if ($LASTEXITCODE -ne 0) { throw "Type check failed; stop here" }
npm test
if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed; stop here" }
npm run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed; stop here" }
Set-Location ..\backend
$env:ASSESSMENT_ALLOW_TEST_DATABASE_CREATION = "1"
$env:ASSESSMENT_ALLOW_TEST_MEDIA_CREATION = "1"
python ..\scripts\verify_browser.py
if ($LASTEXITCODE -ne 0) { throw "Corrected browser gate failed; stop here" }
```

Expected: workspace 0.12.1, Vitest 4.1.12, zero reported npm vulnerabilities, 17 frontend tests, successful build, three Playwright scenarios passed, one Python harness test passed and BROWSER_GATE=PASS. Chromium/Playwright pins are unchanged; the browser is already installed. Node must be at least 22.12.0; your v22.22.0 meets this.

No need to rerun the 11-minute backend suite for this frontend-only correction. If the browser gate fails, share its failure section and the referenced artifacts/browser/.../error-context.md files. Do not change timeouts or bypass assertions. Do not run npm audit fix --force; if npm reports new findings, retain the exact audit output for review.

After the browser gate passes, resume normal API/UI readiness and manual checks from P2_007_UPGRADE_WINDOWS.md. Include these correction files in the later normal Git commit. Do not close P2-007 or start P2-008 before actual new-commit CI and local browser acceptance.
