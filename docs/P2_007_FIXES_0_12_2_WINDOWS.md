# P2-007 correction 0.12.2 — saved prompt and narrow layout

Prerequisite: correction 0.12.1 already applied. Your backend 659-test pass and zero-vulnerability Vitest4.1.12 install remain applicable. Dependencies, backend, schema and storage configuration are unchanged; frontend package version becomes 0.12.2.

Owner 0.12.1 browser result: role/tenant scenario passed; seven-type scenario stopped locating a prepopulated textarea; narrow image/conflict scenario reached the document-width assertion and failed. The supplied snapshots show the saved editor exists. Exact getByLabel text matching includes nested textarea text in the installed Playwright implementation; separate for/id labels keep the label independent from the saved value. A new regression checks saved parent/child labels and unique IDs.

Responsive correction uses min-width:0 on grid/flex children and controls, minmax(0,1fr) for single-column grids, wrapping legends/footer and bounded control width. It does not hide horizontal overflow. The browser gate still requires the document to fit its viewport; it now waits for the reload to finish and attaches numeric width/element-class diagnostics if the assertion fails. The exact overflowing element was not available from the owner accessibility snapshot, so local viewport acceptance remains required.

Extract Assessment_P2_007_Fix_v0_12_2.zip outside your repository under D:\school\exam\Assessment\updates\v0_12_2. Stop any ordinary frontend dev server; leave media storage and ClamAV running.

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform\backend"
.venv\Scripts\Activate.ps1
python "D:\school\exam\Assessment\updates\v0_12_2\assessment-p2-007-fix-0.12.2\apply_p2_007_fixes.py" --target "D:\school\exam\Assessment\assessment-platform"
if ($LASTEXITCODE -ne 0) { throw "0.12.2 correction failed; stop here" }
Set-Location ..\frontend
npm run format:check
if ($LASTEXITCODE -ne 0) { throw "Frontend format failed; stop here" }
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
if ($LASTEXITCODE -ne 0) { throw "0.12.2 browser gate failed; stop here" }
```

Expected 18 frontend tests passed, type/format/build passed, three Playwright scenarios passed and BROWSER_GATE=PASS. No npm reinstall, audit-force fix, Chromium download, backend-suite rerun or migration is needed for this patch. The existing non-failing Vite config-loader warning remains documented.

If the gate fails, share the failure section. A width failure now prints numeric document/viewport and offending element classes directly in the assertion; its narrow-layout.json is also attached in artifacts/browser. Keep the assertion and timing limits intact. No corrected live browser pass is claimed in the authoring environment.

P2-007 still requires actual browser/manual readiness and new-commit CI before acceptance and P2-008. Follow the original Windows guide after the gate passes.
