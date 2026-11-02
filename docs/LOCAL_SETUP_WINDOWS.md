# Current Windows setup

Version 0.4.0 uses P1_004_UPGRADE_WINDOWS.md for the current update, migration, grant refresh, tests and worker sequence. The P1 003 guide remains historical context for initial institution/API-role provisioning; do not repeat bootstrap or password creation for an existing installation.

For a fresh local installation, install backend/requirements-dev.lock, create backend/.env with a dedicated PostgreSQL assessment database owner URL, apply all migrations and provision the API runtime role using app.manage create-runtime-role --write-env. Provision the first institution using app.manage bootstrap with your actual email. Then provision the worker and run current acceptance as described in the P1 004 guide. Never copy .env.example over working private credentials.

Locally installed PostgreSQL is supported; Docker is optional. The supplied infrastructure/compose.yaml remains a loopback development example, not a production deployment recipe.
