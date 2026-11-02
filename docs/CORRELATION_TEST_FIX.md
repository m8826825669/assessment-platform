# Version 0.4.1 credential error test correction

The previous integration assertion incorrectly required per-request correlation fields to be identical. The corrected test still compares every stable error field and additionally verifies valid unique UUIDs, body/header correlation, matching request URNs and the exact generic credential error.

This is a test-only change. There is no migration, password reset, role change or dependency update.

Extract this archive separately into D:\school\exam\Assessment\updates\v0_4_1. From the existing activated backend terminal, run:

```powershell
python "D:\school\exam\Assessment\updates\v0_4_1\assessment-platform\fix_correlation_test.py"
if ($LASTEXITCODE -ne 0) { throw "Patch failed; stop here" }
python -m pytest tests/integration/test_identity_tenancy.py::test_wrong_password_and_unknown_user_have_identical_responses -q --require-postgres
if ($LASTEXITCODE -ne 0) { throw "Focused test failed; stop here" }
python -m pytest -q -ra --require-postgres
```

The patcher changes only the obsolete assertion, retains a backup of the original test, preserves LF/CRLF line endings and is safe to repeat. It uses the current directory as backend unless --backend is specified. Do not run the full source updater just to apply this test fix. The full source archive already contains the corrected test.

Expected focused result: one passed. Expected full result: 227 passed, no skipped tests. Runtime audit/outbox acceptance remains open until the full suite and main database worker smoke pass.
