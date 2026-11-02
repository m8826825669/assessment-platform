# P2-005 corrections / source 0.10.1

Owner real-service result: 569 passed, three failed, 522.02 seconds. P2-005 remains unaccepted. The three failures exposed a dependent RLS policy in downgrade, MinIO implicit latest-read permission, and an invalid assumption about appended EICAR detection. Worker remained healthy. No successful full gate is claimed for 0.10.0.

## Changes

- Drop media_read explicitly before dropping question_version_media in 0007's downgrade. Only the downgrade body changes; the upgrade AST is identical and accepted migrations 0001–0006 stay byte-identical. 0007 is still under acceptance. Applying these source corrections does not execute a migration or modify the main database. Do NOT downgrade or recreate your application database.
- MinIO treats GetObjectVersion as implicitly enabling GetObject. Split upload/read grants and require nonempty explicit s3:versionid, excluding null, on the read grant. Refresh only the existing generated application policy; keep the bucket, objects, credentials and database unchanged. Live tests must prove version reads work while latest reads fail.
- Parse the first structural PNG IEND/JPEG EOI and reject trailing data, including duplicate appended terminators. Keep actual decoder verification and progressive JPEG support. Recheck image validation when using stored bytes so legacy clean metadata cannot bypass tightened format rules. An invalid legacy object fails closed; no old metadata is silently rewritten.
- EICAR's detection guarantee covers its standard file beginning, not arbitrary bytes appended to another format. Keep the actual raw EICAR scanner test and assert that malformed PNG-plus-suffix is rejected at upload with no byte capture. Controlled-adapter integration tests separately exercise rejected scan persistence/permissions. No claim that ClamAV detects every embedded signature or all malware.

## Apply targeted patch

Stop API/worker processes; keep the healthy local storage/scanner containers running. Extract Assessment_Platform_P2_005_Fixes_v0_10_1.zip into `D:\school\exam\Assessment\updates\v0_10_1`.

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform\backend"
.venv\Scripts\Activate.ps1
python "D:\school\exam\Assessment\updates\v0_10_1\assessment-media-fix-0.10.1\apply_media_fixes.py" --target "D:\school\exam\Assessment\assessment-platform"
if ($LASTEXITCODE -ne 0) { throw "Media correction patch failed; stop here" }
python -m app.media.manage refresh-policy
if ($LASTEXITCODE -ne 0) { throw "Storage policy refresh failed; stop here" }
python -m app.media.manage status
if ($LASTEXITCODE -ne 0) { throw "Media status failed; stop here" }
```

Hidden prompts use the same local compose storage operator credentials used for provisioning. Do not run provision again. Refresh-policy updates only the known assess_* principal's same-named policy after checking its assignment. It does not rotate credentials, create a bucket, delete objects or write .env. The patch backs up replaced source, validates known old/new hashes, preserves .env/.git/environments and the already applied HTTP/1 build adjustment, and refreshes only affected checksum entries. No new dependencies, database grant refresh or application-schema migration are required for this correction.

## Focused then full verification

```powershell
$env:ASSESSMENT_TEST_ADMIN_URL = python -c "from app.config import Settings; print(Settings().migration_url.get_secret_value())"
if ($LASTEXITCODE -ne 0) { throw "Test configuration failed; stop here" }
$env:ASSESSMENT_ALLOW_TEST_DATABASE_CREATION = "1"
$env:ASSESSMENT_ALLOW_TEST_MEDIA_CREATION = "1"
python -m pytest tests/test_media.py tests/integration/test_database.py::test_migration_downgrade_and_reupgrade_on_disposable_database tests/integration/test_media_storage_live.py -q -ra --require-postgres
if ($LASTEXITCODE -ne 0) { throw "Focused correction verification failed; stop here" }
python ..\scripts\verify.py --local-postgres
if ($LASTEXITCODE -ne 0) { throw "Full P2-005 verification failed; stop here" }
python -m app.worker --status
```

Expected focused suite: 47 tests. Full collection: 581 tests, zero skips, VERIFICATION=PASS. Signature/storage/real database checks remain mandatory. If any test fails, retain the failure section and stop; never bypass IAM/checksum/scan guards to pass. No application DB downgrade is part of these instructions. After full success, restart API, verify readiness and inspect/commit/push all pending P2-005 source including the HTTP/1 Dockerfile adjustment. Actual new-commit CI is still required before acceptance.

References: https://www.eicar.org/download-anti-malware-testfile/ ; https://github.com/minio/pkg/blob/v3.1.3/policy/actionset.go .
