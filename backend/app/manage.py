"""Local operator provisioning; passwords are prompted, never command-line arguments."""

import argparse
import os
import sys
from getpass import getpass
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from dotenv import set_key
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.database import EXPECTED_DATABASE_REVISION
from app.db.models import AuthSession, Institution, Membership, OutboxDelivery, OutboxEvent, User
from app.db.provisioning import create_runtime, create_worker, grant_runtime, grant_worker
from app.identity.permissions import ROLE_PERMISSIONS
from app.identity.security import hash_password, validate_new_password
from app.identity.service import security_event


def configure_keys(path: Path, values: dict[str, str], backup_name: str) -> None:
    """Preserve the original file if either rewrite fails; never print its contents."""
    original = path.read_bytes() if path.is_file() else b""
    backup = path.with_name(backup_name)
    if path.is_file() and not backup.exists():
        descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(original)
    temporary = path.with_name(".env.runtime-" + uuid4().hex)
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(original)
        for key, value in values.items():
            set_key(str(temporary), key, value, encoding="utf-8-sig")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def configure_env(path: Path, migration_url: str, runtime_url: str) -> None:
    configure_keys(
        path,
        {"ASSESSMENT_MIGRATION_DATABASE_URL": migration_url, "ASSESSMENT_DATABASE_URL": runtime_url},
        ".env.pre-p1-003",
    )


def read_password(label="Password"):
    first = getpass(label + ": ")
    second = getpass("Confirm password: ")
    if first != second:
        raise ValueError("Passwords do not match")
    validate_new_password(first)
    return first


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    boot = sub.add_parser("bootstrap")
    boot.add_argument("--slug", required=True)
    boot.add_argument("--name", required=True)
    boot.add_argument("--email", required=True)
    boot.add_argument("--display-name", required=True)
    user = sub.add_parser("create-user")
    user.add_argument("--email", required=True)
    user.add_argument("--display-name", required=True)
    reset = sub.add_parser("reset-password")
    reset.add_argument("--email", required=True)
    member = sub.add_parser("grant-membership")
    member.add_argument("--tenant", type=UUID, required=True)
    member.add_argument("--user", type=UUID, required=True)
    member.add_argument("--role", choices=sorted(ROLE_PERMISSIONS), required=True)
    runtime = sub.add_parser("create-runtime-role")
    runtime.add_argument("--role", default="assessment_runtime")
    runtime.add_argument("--write-env", action="store_true")
    grants = sub.add_parser("grant-runtime")
    grants.add_argument("--role", default="assessment_runtime")
    worker = sub.add_parser("create-worker-role")
    worker.add_argument("--role", default="assessment_worker")
    worker.add_argument("--write-env", action="store_true")
    worker_grants = sub.add_parser("grant-worker")
    worker_grants.add_argument("--role", default="assessment_worker")
    replay = sub.add_parser("requeue-outbox")
    replay.add_argument("--event", type=UUID, required=True)
    replay.add_argument(
        "--reason-code", choices=["handler_fixed", "transient_failure_reviewed"], required=True
    )
    return result


def run(args):
    settings = Settings()
    url = make_url(settings.migration_url.get_secret_value())
    if args.command in {"create-runtime-role", "grant-runtime", "create-worker-role", "grant-worker"}:
        password = (
            read_password(
                "New worker database password"
                if args.command == "create-worker-role"
                else "New runtime database password"
            )
            if args.command in {"create-runtime-role", "create-worker-role"}
            else None
        )
        with psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False)
        ) as connection:
            if connection.execute("SELECT version_num FROM alembic_version").fetchall() != [
                (EXPECTED_DATABASE_REVISION,)
            ]:
                raise ValueError("Apply the latest migration before provisioning runtime credentials")
            if args.command == "create-worker-role":
                create_worker(connection, args.role, password)
            elif args.command == "grant-worker":
                grant_worker(connection, args.role)
            elif password is not None:
                create_runtime(connection, args.role, password)
            else:
                grant_runtime(connection, args.role)
        if args.command == "create-runtime-role" and args.write_env:
            try:
                configure_env(
                    Path.cwd() / ".env",
                    settings.migration_url.get_secret_value(),
                    url.set(username=args.role, password=password).render_as_string(hide_password=False),
                )
            except OSError:
                print(
                    "RUNTIME_ROLE=CREATED; ENV_UPDATE=FAILED. The original configuration was retained; configure it privately before starting the API.",
                    file=sys.stderr,
                )
                raise SystemExit(1) from None
            print("ENV_CONFIGURATION=UPDATED; keep .env and its backup private")
        if args.command == "create-worker-role" and args.write_env:
            try:
                configure_keys(
                    Path.cwd() / ".env",
                    {
                        "ASSESSMENT_WORKER_DATABASE_URL": url.set(
                            username=args.role, password=password
                        ).render_as_string(hide_password=False)
                    },
                    ".env.pre-p1-004",
                )
            except OSError:
                print(
                    "WORKER_ROLE=CREATED; ENV_UPDATE=FAILED; configure credentials privately", file=sys.stderr
                )
                raise SystemExit(1) from None
            print("ENV_CONFIGURATION=UPDATED; API and migration credentials unchanged")
        print("WORKER_ROLE=READY" if "worker" in args.command else "RUNTIME_ROLE=READY")
        return

    raw_password = read_password() if args.command in {"bootstrap", "create-user", "reset-password"} else None
    engine = create_engine(url, hide_parameters=True)
    try:
        with Session(engine) as session, session.begin():
            if args.command in {"bootstrap", "create-user"}:
                email = args.email.strip().lower()
                if email.count("@") != 1 or any(x.isspace() for x in email):
                    raise ValueError("Invalid email")
                if session.scalar(select(User.id).where(User.email == email)):
                    raise ValueError("User already exists; this command never overwrites credentials")
                user = User(
                    email=email, display_name=args.display_name, password_hash=hash_password(raw_password)
                )
                session.add(user)
                session.flush()
                security_event(session, "operator.user_created", subject=str(user.id))
                if args.command == "bootstrap":
                    tenant = Institution(slug=args.slug, name=args.name)
                    # Supply UUID before insert so forced policies also work for a non-superuser migration owner.
                    tenant.id = uuid4()
                    session.execute(
                        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant.id)}
                    )
                    session.add(tenant)
                    session.flush()
                    member = Membership(tenant_id=tenant.id, user_id=user.id, role="admin")
                    session.add(member)
                    session.flush()
                    security_event(
                        session,
                        "operator.membership_created",
                        tenant=tenant.id,
                        subject=str(member.id),
                        after={"user_id": str(user.id), "role": "admin", "status": "active"},
                    )
                    security_event(
                        session, "operator.institution_created", tenant=tenant.id, subject=str(tenant.id)
                    )
                    print("TENANT_ID=" + str(tenant.id))
                print("USER_ID=" + str(user.id))
            elif args.command == "grant-membership":
                session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(args.tenant)}
                )
                if session.get(Institution, args.tenant) is None or session.get(User, args.user) is None:
                    raise ValueError("Institution or user does not exist")
                member = Membership(tenant_id=args.tenant, user_id=args.user, role=args.role)
                session.add(member)
                session.flush()
                security_event(
                    session,
                    "operator.membership_created",
                    tenant=args.tenant,
                    subject=str(member.id),
                    after={"user_id": str(args.user), "role": args.role, "status": "active"},
                )
            elif args.command == "requeue-outbox":
                job = session.scalar(
                    select(OutboxDelivery).where(OutboxDelivery.event_id == args.event).with_for_update()
                )
                if job is None or job.status != "dead":
                    raise ValueError("Only a dead outbox event can be requeued")
                event = session.get(OutboxEvent, args.event)
                if event.tenant_id is not None:
                    session.execute(
                        text("SELECT set_config('app.tenant_id', :tenant, true)"),
                        {"tenant": str(event.tenant_id)},
                    )
                before = {"status": "dead", "attempts": job.attempts}
                job.status, job.attempts, job.last_error_code = "pending", 0, None
                job.available_at = session.scalar(select(func.clock_timestamp()))
                security_event(
                    session,
                    "operator.outbox_requeued",
                    tenant=event.tenant_id,
                    subject=str(event.id),
                    before=before,
                    after={"status": "pending", "attempts": 0, "reason_code": args.reason_code},
                )
            elif args.command == "reset-password":
                user = session.scalar(
                    select(User).where(User.email == args.email.strip().lower()).with_for_update()
                )
                if user is None:
                    raise ValueError("User does not exist")
                user.password_hash = hash_password(raw_password)
                session.execute(
                    update(AuthSession)
                    .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                    .values(revoked_at=func.now())
                )
                security_event(session, "operator.password_reset", subject=str(user.id))
        print("OPERATION=COMMITTED")
    finally:
        engine.dispose()


def main():
    args = parser().parse_args()
    try:
        run(args)
    except ValueError as error:
        print("OPERATION=FAILED: " + str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        # Never echo database exceptions: connection details or role passwords may be present.
        print(
            "OPERATION=FAILED: check migration state, database privileges and input; no credentials were changed by an uncommitted transaction",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
