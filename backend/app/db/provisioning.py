"""Explicit operator actions. Never imported as API endpoints."""

import re

from psycopg import Connection, sql

ROLE_NAME = re.compile(r"^assessment_[a-z0-9_]{1,50}$")


def restricted_role(connection: Connection, role: str):
    if not ROLE_NAME.fullmatch(role):
        raise ValueError(
            "Use an assessment_ prefixed role name containing lowercase letters, digits and underscores"
        )
    flags = connection.execute(
        "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolreplication FROM pg_roles WHERE rolname = %s",
        (role,),
    ).fetchone()
    if flags is None or any(flags):
        raise ValueError("Role must exist and have no elevated PostgreSQL privileges")
    if connection.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=%s)",
        (role,),
    ).fetchone()[0]:
        raise ValueError("Runtime role must not inherit or belong to other roles")
    owns_objects = connection.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner WHERE r.rolname=%s) "
        "OR EXISTS (SELECT 1 FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba WHERE r.rolname=%s) "
        "OR EXISTS (SELECT 1 FROM pg_namespace n JOIN pg_roles r ON r.oid=n.nspowner WHERE r.rolname=%s)",
        (role, role, role),
    ).fetchone()[0]
    if owns_objects:
        raise ValueError("Runtime role must not own databases, schemas or relations")
    return sql.Identifier(role)


def grant_connection(connection: Connection, identifier) -> None:
    database = connection.execute("SELECT current_database()").fetchone()[0]
    connection.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), identifier)
    )
    connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(identifier))


def grant_runtime(connection: Connection, role: str) -> None:
    identifier = restricted_role(connection, role)
    if connection.execute(
        "SELECT has_table_privilege(%s, 'outbox_deliveries', 'SELECT') OR has_table_privilege(%s, 'consumer_receipts', 'INSERT')",
        (role, role),
    ).fetchone()[0]:
        raise ValueError("Use a separate API role; worker privileges are already present")
    grant_connection(connection, identifier)
    connection.execute(
        sql.SQL(
            "GRANT SELECT ON alembic_version, users, institutions, memberships, auth_sessions, login_buckets, audit_records TO {}"
        ).format(identifier)
    )
    connection.execute(sql.SQL("GRANT UPDATE (password_hash) ON users TO {}").format(identifier))
    connection.execute(sql.SQL("GRANT UPDATE (name) ON institutions TO {}").format(identifier))
    connection.execute(
        sql.SQL("GRANT INSERT, UPDATE ON auth_sessions, login_buckets TO {}").format(identifier)
    )
    connection.execute(
        sql.SQL(
            "GRANT INSERT ON memberships, security_events, audit_records, outbox_events, outbox_deliveries TO {}"
        ).format(identifier)
    )
    connection.execute(sql.SQL("GRANT UPDATE (role, status) ON memberships TO {}").format(identifier))


def grant_worker(connection: Connection, role: str) -> None:
    identifier = restricted_role(connection, role)
    if connection.execute(
        "SELECT has_table_privilege(%s, 'users', 'SELECT') OR has_table_privilege(%s, 'audit_records', 'INSERT')",
        (role, role),
    ).fetchone()[0]:
        raise ValueError("Use a separate worker role; API privileges are already present")
    grant_connection(connection, identifier)
    connection.execute(
        sql.SQL(
            "GRANT SELECT ON alembic_version, outbox_events, outbox_deliveries, consumer_receipts TO {}"
        ).format(identifier)
    )
    connection.execute(sql.SQL("GRANT INSERT ON consumer_receipts TO {}").format(identifier))
    connection.execute(
        sql.SQL(
            "GRANT UPDATE (status, attempts, available_at, lease_token, lease_expires_at, delivered_at, last_error_code) ON outbox_deliveries TO {}"
        ).format(identifier)
    )


def create_role(connection: Connection, role: str, password: str, grant) -> None:
    if not ROLE_NAME.fullmatch(role):
        raise ValueError("Use an assessment_ prefixed role name")
    if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
        raise ValueError("Role already exists; refresh grants or choose a fresh dedicated name")
    connection.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD {}"
        ).format(sql.Identifier(role), sql.Literal(password))
    )
    grant(connection, role)


def create_runtime(connection: Connection, role: str, password: str) -> None:
    create_role(connection, role, password, grant_runtime)


def create_worker(connection: Connection, role: str, password: str) -> None:
    create_role(connection, role, password, grant_worker)
