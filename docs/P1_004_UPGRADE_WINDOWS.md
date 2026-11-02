# P1 004 transactional audit and outbox upgrade

P1 003 is complete based on your Windows PostgreSQL result of 134 passed, restricted-role readiness, and the verified login/read/logout/revocation sequence. This package implements P1 004. Its new database acceptance gate remains pending until the full new suite passes locally.

## 1 Apply the source update

Stop the running development API with Ctrl+C before updating or migrating. Extract the new archive separately into `D:\school\exam\Assessment\updates\v0_4`. It contains the assessment-platform folder. From the existing activated backend terminal:

```powershell
python "D:\school\exam\Assessment\updates\v0_4\assessment-platform\apply_update.py" --target "D:\school\exam\Assessment\assessment-platform"
if ($LASTEXITCODE -ne 0) { throw "Source update failed; stop here" }
cd D:\school\exam\Assessment\assessment-platform\backend
python -m pip install -r requirements-dev.lock
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed; stop here" }
```

The updater verifies both existing migrations byte for byte, backs up overwritten source and preserves .env, .venv and Git data. It does not connect to PostgreSQL. Do not copy .env.example over your working configuration. Source backups do not replace database backups.

## 2 Upgrade the database and refresh API grants

```powershell
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Migration failed; stop here" }
python -m alembic current
python -m alembic check
if ($LASTEXITCODE -ne 0) { throw "Schema comparison failed; stop here" }
python -m app.manage grant-runtime --role assessment_runtime
if ($LASTEXITCODE -ne 0) { throw "Grant refresh failed; stop here" }
```

Expected head: `0003_audit_outbox`. Alembic and the grant command use the existing migration credentials. The grant refresh adds the new table permissions to assessment_runtime; it does not recreate the role or change its password. Use your custom dedicated API role name if you previously chose a different one.

Before the grant refresh, readiness may report runtime_role missing_grants. That is intentional. Keep the API stopped until migration and grants finish. Existing users, memberships, passwords, sessions and legacy security events are preserved. New audit history begins with this version; no before/after data is invented for old events.

## 3 Run full acceptance tests

```powershell
$env:ASSESSMENT_TEST_ADMIN_URL = python -c "from app.config import Settings; print(Settings().migration_url.get_secret_value())"
if ($LASTEXITCODE -ne 0) { throw "Configuration failed" }
$env:ASSESSMENT_ALLOW_TEST_DATABASE_CREATION = "1"
python -m pytest -q -ra --require-postgres
if ($LASTEXITCODE -ne 0) { throw "Acceptance tests failed; stop here" }
python -m ruff check .
python -m ruff format --check .
```

Expected current collection: 227 tests, all passed with no skips. One existing Starlette/httpx dependency deprecation warning remains. The harness creates only random disposable test databases and API/worker roles; it does not seed or change the main assessment database. The test administrator still needs CREATEDB, CREATEROLE and grant authority. Never grant these to the API or worker role.

The added database tests cover transactional rollback, tenant audit visibility, forbidden audit modifications, coherent audit/outbox scope, concurrent job claims, expired leases, stale acknowledgements, duplicate receipt handling, bounded retries, dead-letter handling, reviewed requeue, role separation and missing grants.

## 4 Provision a separate worker role

After the tests pass:

```powershell
python -m app.manage create-worker-role --role assessment_worker --write-env
if ($LASTEXITCODE -ne 0) { throw "Worker provisioning failed; stop here" }
```

Choose a new private database password at the hidden prompts. It is separate from your API database password and application login password. This command adds ASSESSMENT_WORKER_DATABASE_URL to .env, leaving the API and migration URLs unchanged. The previous .env is backed up privately as .env.pre-p1-004. No password or connection URL is printed.

If this dedicated worker role already exists from an earlier successful attempt, do not recreate it or overwrite its password. Use `python -m app.manage grant-worker --role assessment_worker` to refresh grants, and retain the existing worker URL. A name collision with an unrelated role requires choosing a fresh dedicated name. Owner, administrative and inherited roles are rejected.

The worker can read immutable outbox envelopes, update delivery state and insert deduplication receipts. It cannot read user credentials, manage memberships or rewrite audit/envelope/receipt history. The API can append new jobs but cannot run queue consumption operations.

## 5 Verify API and worker operation

Start the API:

```powershell
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-proxy-headers
```

In a second terminal, call `Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready`; expect postgresql, schema and runtime_role all equal to ok. The API readiness check covers the producer and schema, not an assertion that a worker process is running.

Sign in through http://127.0.0.1:8000/docs using the existing administrator. Do not bootstrap the institution again. Login/logout and later membership changes now write audit entries and queue outbox jobs in their business transaction. GET /api/v1/tenants/{tenant_id}/audit is available to institution administrators. It returns only tenant history, so it may initially be empty: global login events and pre-upgrade legacy history are not included.

From another activated backend terminal:

```powershell
python -m app.worker --status
python -m app.worker --once --limit 100
python -m app.worker --status
```

Expected: queued jobs become delivered with dead count zero. Repeating --once after the queue drains should process no extra work and preserve delivery counts. The commands print state totals, not event bodies, passwords or bearer tokens. This version performs a local database receipt effect only. It sends no email, messages or webhooks.

Worker exit code 0 indicates the command completed with no dead jobs; 1 indicates configuration/database failure; 2 indicates dead jobs requiring review. --once is a bounded pass, not a daemon. Scheduling, process supervision and production monitoring remain later operational work. Pending jobs beyond the selected limit require another pass.

## 6 Handle a dead event only after review

Inspect the failure using a trusted operator database session. A bounded, metadata-only diagnostic is:

```sql
SELECT event_id, attempts, max_attempts, last_error_code
FROM outbox_deliveries
WHERE status = 'dead'
ORDER BY available_at, event_id
LIMIT 20;
```
 Do not repeatedly retry a permanently invalid event without fixing its cause. An operator can requeue a reviewed dead event using migration credentials:

```powershell
$eventId = Read-Host "Enter the reviewed dead event UUID"
python -m app.manage requeue-outbox --event "$eventId" --reason-code handler_fixed
```

Alternatively use reason code transient_failure_reviewed when appropriate. Live/pending/delivered jobs are not eligible. Requeue resets its attempt budget and records an operator audit entry plus a new outbox event in the same transaction. It cannot erase the original event or receipt. A receipt mismatch still requires investigation; requeue is not a way to overwrite it.

## 7 Error contract and completion evidence

Exceptions now use application/problem+json, with code and request_id at the top level. Previous clients reading detail.code must move to code. Success responses and diagnostic readiness reports keep their existing shapes. Every response has an X-Request-ID generated by the server. Passwords, tokens, raw validation input, query strings and database exception messages are not reflected in error bodies.

Close P1 004 only after recording 227 passing tests, current head/schema comparison, clean Ruff checks, readiness after grant refresh, and a local worker drain/repeat smoke. P1 005, developer environment and CI, follows. P1 overall remains open.
