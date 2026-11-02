> For an already-applied 0.10.0 installation, use P2_005_FIXES_WINDOWS.md instead of re-provisioning or changing the application database.

# P2-005 Windows upgrade and live verification

Accepted predecessor: 5b3e6a8, P2-004, 502 local tests and green workflow #5. New source/API 0.10.1; head 0007_authoring_media. Six earlier migrations and content.v1 remain unchanged. Old versions have no fabricated media attachments.

This increment adds new local infrastructure. Use Docker Desktop with Linux containers/WSL2, or stop and resolve that prerequisite first. ClamAV's upstream guidance calls for about 4 GiB for its container; allow additional resources for the object store, Go source build and existing PostgreSQL. First build downloads source/dependencies and can take several minutes. Existing applications/VPS services are not reused. Do not apply this fixture to production hosting.

## 1. Source and environment

Stop API/worker processes. Keep your normal database backup; updater backup is source only. Download/extract Assessment_Platform_P2_005_v0_10.zip separately into `D:\school\exam\Assessment\updates\v0_10`. Review existing work:

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform"
git status --short
git log -1 --oneline
docker version
if ($LASTEXITCODE -ne 0) { throw "Docker Linux-container prerequisites are not ready; stop here" }
```

Apply after reviewing unexpected changes:

```powershell
python "D:\school\exam\Assessment\updates\v0_10\assessment-platform\apply_update.py" --target "D:\school\exam\Assessment\assessment-platform"
if ($LASTEXITCODE -ne 0) { throw "Source update failed; stop here" }
Set-Location backend
.venv\Scripts\Activate.ps1
python ..\scripts\setup_dev.py
if ($LASTEXITCODE -ne 0) { throw "Setup failed; stop here" }
```

Do not replace your .env or print its contents. Configure only nonsecret media settings:

```powershell
@'
from pathlib import Path
from app.manage import configure_keys
configure_keys(Path('.env'), {
    'ASSESSMENT_MEDIA_ENABLED': 'false',
    'ASSESSMENT_MEDIA_ENDPOINT': '127.0.0.1:19000',
    'ASSESSMENT_MEDIA_SECURE': 'false',
    'ASSESSMENT_MEDIA_REGION': 'us-east-1',
    'ASSESSMENT_MEDIA_BUCKET': 'assessment-authoring',
    'ASSESSMENT_MEDIA_SCANNER_HOST': '127.0.0.1',
    'ASSESSMENT_MEDIA_SCANNER_PORT': '13310',
    'ASSESSMENT_MEDIA_SIGNATURE_MAX_AGE_DAYS': '7',
}, '.env.pre-p2-005-configuration')
print('MEDIA_CONFIGURATION=READY; database credentials unchanged')
'@ | python
if ($LASTEXITCODE -ne 0) { throw "Media configuration failed; stop here" }
```

## 2. Start separate local media services

From backend:

```powershell
docker compose -f ..\infrastructure\compose.media.yaml up -d --build
if ($LASTEXITCODE -ne 0) { throw "Media service build/start failed; stop here" }
docker compose -f ..\infrastructure\compose.media.yaml ps
Invoke-RestMethod http://127.0.0.1:19000/minio/health/live
Invoke-RestMethod http://127.0.0.1:19010/minio/health/live
docker compose -f ..\infrastructure\compose.media.yaml exec -T clamav clamdscan --ping=1
```

MinIO health endpoints can return an empty successful body. Wait for ClamAV to load/update its signatures; repeat the ping if it is still starting. Do not disable scanning to pass a gate. Useful scanner diagnostics:

```powershell
docker compose -f ..\infrastructure\compose.media.yaml logs --tail 80 clamav
```

Ports: 19000 application storage; 19001 local operator console; 19010 independent disposable test storage; 13310 ClamAV. All published ports bind loopback only. The dedicated media compose does not start/change PostgreSQL. Development-only fixture operator credentials are defined in that compose, never copied to the API as application credentials.

Provision a NEW application bucket and generated restricted credential:

```powershell
python -m app.media.manage provision
if ($LASTEXITCODE -ne 0) { throw "Private storage provisioning failed; stop here" }
```

At hidden prompts use the local compose operator access key `assessment_storage_operator` and its development secret `assessment_storage_local_only`. The command creates the new bucket, enables versioning, creates a restricted storage user/policy, privately writes generated application credentials to .env and enables media. Database credentials are unchanged. It refuses an existing bucket; do not repeatedly provision/erase an existing media store to recover an error. A partial provisioning failure needs operator inspection before retrying. Do not share .env, backups or credentials.

```powershell
python -m app.media.manage status
if ($LASTEXITCODE -ne 0) { throw "Storage/scanner readiness failed; stop here" }
```

Expected both media_storage and media_scanner ok. Stale signatures (over seven days) must be updated through FreshClam; do not extend freshness beyond the supported bound or replace the scanner with a fake. If services/build/signature updates fail, share redacted status/error output and resolve prerequisites before migration/acceptance.

## 3. Schema, grants and strict verification

```powershell
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Migration failed; stop here" }
python -m alembic current
python -m alembic check
if ($LASTEXITCODE -ne 0) { throw "Schema comparison failed; stop here" }
python -m app.manage grant-runtime --role assessment_runtime
if ($LASTEXITCODE -ne 0) { throw "Runtime grants failed; stop here" }
python -m app.manage grant-worker --role assessment_worker
if ($LASTEXITCODE -ne 0) { throw "Worker grant check failed; stop here" }
$env:ASSESSMENT_ALLOW_TEST_DATABASE_CREATION = "1"
$env:ASSESSMENT_ALLOW_TEST_MEDIA_CREATION = "1"
python ..\scripts\verify.py --local-postgres
if ($LASTEXITCODE -ne 0) { throw "P2-005 strict verification failed; stop here" }
python -m app.worker --status
if ($LASTEXITCODE -ne 0) { throw "Worker status failed; stop here" }
```

Expected 0007_authoring_media head, clean metadata comparison, both roles ready, **581 tests passed, zero skips**, VERIFICATION=PASS. The full gate now needs real PostgreSQL, dedicated test object storage and ClamAV. Missing services must fail, not skip. Existing TestClient warning remains tracked.

Live tests create only random assessment-test-* buckets, separate restricted test users/policies and disposable databases. They verify anonymous/list/delete denials, overwrite protection through exact version references, and standard harmless EICAR antivirus detection. Test objects/users/policies are cleaned up; no application media is removed. No new application institution or question is bootstrapped. API SQL invariants also have isolated controlled-adapter tests, explicitly distinct from real service tests.

## 4. Restart and acceptance

Restart the API with the existing Uvicorn command, using the updated environment. In another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready
```

Expected postgresql/schema/runtime_role/media_storage/media_scanner all ok. Share these outputs, strict test summary and worker status before closing the local gate.

After a successful local gate:

```powershell
Set-Location "D:\school\exam\Assessment\assessment-platform"
git diff --stat
git status --short
git add .github/workflows/ci.yml AGENTS.md README.md apply_update.py backend docs infrastructure
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw "Staged check failed; stop here" }
git diff --cached --stat
git commit -m "Add private scanned authoring media and immutable version attachments"
if ($LASTEXITCODE -ne 0) { throw "Commit failed; stop here" }
git push origin main
if ($LASTEXITCODE -ne 0) { throw "Push failed; stop here" }
git log -1 --oneline
```

Inspect https://github.com/m8826825669/assessment-platform/actions for this new commit. Three PostgreSQL/Python jobs now also build isolated storage and run real ClamAV checks; Windows remains the portable job. All must pass. Record P2-005 acceptance only then; P2-006 imports follows. No production deployment occurs.

## Recovery boundaries

Never stamp head, alter an accepted migration, use owner database credentials for the API, grant storage administration to the API or mark files clean manually. Source rollback does not undo schema or external storage. Downgrade destroys media metadata/references and is for disposable databases only. Do not run `docker compose down -v` against application media; its persistent volume contains immutable files. The disposable test store can be recreated independently, but never delete application media to repair a failed test. Failed external PUT/SQL commits can leave inaccessible orphan versions; reconciliation/retention/backup needs an explicit reviewed policy.
