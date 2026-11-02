# P2-007 correction 0.12.3 — table label containment

Prerequisite:0.12.2 applied. Owner output now proves the full seven-type import/author/reviewer/coordinator/immutable-snapshot scenario and tenant/role scenario pass. Only the390px width assertion fails: document474px, body390px, no ordinary outside-table offending elements. Backend659 pass, frontend18/type/format/build and prior zero-audit result remain applicable.

The table actions used absolutely positioned sr-only spans for question titles without a local containing block. They can contribute root scroll overflow outside the table's scrollport. Replace those spans with an equivalent explicit aria-label on each action button, keep the arrow decorative, and establish position:relative on the table scrollport. Visible content and accessible question names remain available; the table can still scroll horizontally. No global overflow:hidden or assertion relaxation is used. This is a code-supported cause consistent with the supplied geometry; actual corrected width must still be checked by the owner browser gate.

Width diagnostics now inspect positioned table descendants and shadow DOM as well, retaining document.scrollWidth<=innerWidth and the existing scenario timeout. If another source remains, the failure reports its class, positioning and containing-block/shadow status without logging content or credentials.

Extract Assessment_P2_007_Fix_v0_12_3.zip outside the repository under D:\school\exam\Assessment\updates\v0_12_3. Stop an ordinary frontend dev server; keep private storage/ClamAV running.

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform\backend"
.venv\Scripts\Activate.ps1
python "D:\school\exam\Assessment\updates\v0_12_3\assessment-p2-007-fix-0.12.3\apply_p2_007_fixes.py" --target "D:\school\exam\Assessment\assessment-platform"
if ($LASTEXITCODE -ne 0) { throw "0.12.3 correction failed; stop here" }
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
if ($LASTEXITCODE -ne 0) { throw "0.12.3 browser gate failed; stop here" }
```

Expected18 frontend tests and successful type/format/build; all3 browser scenarios,1 Python harness test and BROWSER_GATE=PASS. No dependencies changed, so no npm reinstall/audit-force fix/Chromium download, migration or full backend rerun is needed. API/backend stays0.12.0 and schema0008. Existing non-failing Vite config-loader advisory remains tracked.

Share the final browser output. If width still fails, share its numeric diagnostic section; do not remove the viewport assertion or increase timeouts. P2-007 still needs manual readiness checks and actual new-commit CI before acceptance/P2-008. No production deployment is authorized by this correction.
