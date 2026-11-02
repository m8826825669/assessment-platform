# P1 003 identity and tenant enforcement upgrade

Roadmap v1.0 remains the controlling scope. Your P1 002 result was 57 passed, with migration 0001_foundation and clean Ruff checks. This package implements P1 003; its new PostgreSQL gate remains pending until it runs on your local installation.

## 1 Apply source without replacing local configuration

Stop any running development API. Extract this new archive into a separate folder, for example `D:\school\exam\Assessment\updates\v0_3`. The extracted folder contains `assessment-platform\apply_update.py`. Do not extract it over your working project.

In your current PowerShell terminal with the existing virtual environment active, run the following. Adjust only the extracted source path if you chose a different folder.

```powershell
python "D:\school\exam\Assessment\updates\v0_3\assessment-platform\apply_update.py" --target "D:\school\exam\Assessment\assessment-platform"
if ($LASTEXITCODE -ne 0) { throw "Source update failed; stop here" }
cd D:\school\exam\Assessment\assessment-platform\backend
python -m pip install -r requirements-dev.lock
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed; stop here" }
```

The updater verifies the package manifest, checks that your original migration matches, backs up overwritten source files into a sibling folder, and preserves `.env`, `.venv` and Git data. It does not connect to your database. Existing environment backups are not packaged. Source backup is not a database rollback mechanism.

## 2 Apply the additive migration using the current owner account

Your existing `.env` should still point to your locally installed PostgreSQL database `assessment`. Do not copy `.env.example` over it.

```powershell
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Migration failed; stop here" }
python -m alembic current
python -m alembic check
if ($LASTEXITCODE -ne 0) { throw "Schema comparison failed; stop here" }
```

Expected revision: `0002_identity_tenancy`. The migration adds password hashes, membership roles, sessions, login throttling, security events and forced row policies. Existing foundation records are preserved; existing memberships default to candidate and user records without a hash remain unable to log in. The migration does not assign administrator authority to old records or create a default password.

Until the restricted runtime account is configured, readiness will report `runtime_role: unsafe` and business requests will return 503. That is deliberate protection against running the API with migration privileges.

## 3 Run the full database acceptance suite

Use your original local migration/administrative account for test infrastructure. It needs CREATEDB, CREATEROLE and authority to grant privileges in the disposable databases. A normal restricted application account must not receive those powers.

```powershell
$env:ASSESSMENT_TEST_ADMIN_URL = python -c "from app.config import Settings; print(Settings().migration_url.get_secret_value())"
if ($LASTEXITCODE -ne 0) { throw "Configuration failed" }
$env:ASSESSMENT_ALLOW_TEST_DATABASE_CREATION = "1"
python -m pytest -q -ra --require-postgres
if ($LASTEXITCODE -ne 0) { throw "Acceptance tests failed; stop here" }
python -m ruff check .
python -m ruff format --check .
```

Expected current collection: 134 tests, with 134 passed and no skipped tests required. One existing HTTP test-client dependency deprecation warning is expected. The security tests create random `assessment_test_<uuid>` databases and `assessment_test_runtime_<random>` PostgreSQL roles, exercise the API as the restricted roles, and remove the generated resources. Your main assessment database is not seeded or migrated by these tests. Do not point the test harness at a production service.

Required scenarios include wrong credentials, throttling, expiry, logout, password change, membership and institution suspension, role changes with existing sessions, cross institution record IDs, unfiltered database reads under row policies, transaction context cleanup, forbidden DDL and event modification, and concurrent last administrator changes. Existing foundation/domain tests remain in the suite.

Send the migration output and complete test summary before closing P1 003. Fix any failures first. Do not claim isolation based on the locally executed non-database tests alone.

## 4 Provision the restricted runtime account after the tests pass

```powershell
python -m app.manage create-runtime-role --role assessment_runtime --write-env
if ($LASTEXITCODE -ne 0) { throw "Runtime provisioning failed; stop here" }
```

Choose a new database password of at least 15 characters at the hidden prompts. This is a new password for `assessment_runtime`, not a change to your existing PostgreSQL account. The command creates a non-owner login with no superuser, database creation, role creation, replication or RLS bypass privileges. It grants only the required access in your assessment database and removes public schema CREATE from PUBLIC in that dedicated database.

With `--write-env`, your existing URL is retained as `ASSESSMENT_MIGRATION_DATABASE_URL`; the API's `ASSESSMENT_DATABASE_URL` is changed to the new runtime login. The prior `.env` is backed up privately as `.env.pre-p1-003`. Keep both files private. This step is separate from the source updater, which never edits your environment.

If the role name already exists, the command refuses to overwrite its password or attributes. Stop and review the output; use a fresh dedicated name or `grant-runtime` only for an already suitable role. Do not grant the role membership in owner or administrative roles. If process environment variables override `.env`, remove the stale override or start a clean terminal before testing the API.

A safe diagnostic prints only the database username and database name:

```powershell
python -c "from app.config import Settings; from sqlalchemy.engine import make_url; u=make_url(Settings().database_url.get_secret_value()); print('DATABASE_USER=',u.username); print('DATABASE_NAME=',u.database)"
```

Expected user: assessment_runtime. Expected database: assessment. Alembic and operator commands continue to use migration credentials.

## 5 Create the first institution and administrator

There is no public registration endpoint or built-in administrator password. The trusted local operator creates the first institution:

```powershell
python -m app.manage bootstrap --slug pilot-institute --name "Pilot Institute" --email "YOUR_ADMIN_EMAIL" --display-name "Institution Administrator"
```

Replace YOUR_ADMIN_EMAIL with your chosen address. Choose a separate application password at the hidden prompts. The operation creates the institution and administrator in one transaction and reports TENANT_ID and USER_ID on success. It does not overwrite existing users or institutions.

Create another user with `python -m app.manage create-user --email "ADDRESS" --display-name "NAME"`. Provision membership with `python -m app.manage grant-membership --tenant TENANT_UUID --user USER_UUID --role candidate`, or use the administrator membership API once signed in. Administrative APIs operate only on already provisioned users; email invitations and public onboarding are later workflows.

For a forgotten application password, the trusted local operator can run `python -m app.manage reset-password --email "ADDRESS"`. It prompts for a new password, records the action and revokes all of that user's sessions. It does not change PostgreSQL passwords. Email recovery and MFA are not delivered in this increment.

## 6 Start and inspect the API

```powershell
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-proxy-headers
```

In a second terminal, call `Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready`. Expect postgresql, schema and runtime_role all equal to ok. Use http://127.0.0.1:8000/docs to inspect the contract. Login returns a bearer token once; use the OpenAPI Authorize control to test protected endpoints. Treat the token as a password and do not paste it into chat. No frontend has been built yet.

HTTP is only for loopback development. Production requires HTTPS, reviewed proxy configuration and the later launch gates. Default session duration is one hour. Revisit authenticated exam continuity with P4 delivery policies before real exams run. Requests do not trust caller-supplied tenant headers or role claims.

## 7 Completion evidence

Record 134 passing tests, migration head, schema comparison and Ruff results, plus readiness using the restricted account and a successful bootstrap/login/logout journey. P1 003 can then close. P1 004, transactional audit/outbox and broader error contracts, is next; P1 overall remains open until the CI/developer-environment gate also passes.
