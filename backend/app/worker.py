"""Bounded local outbox processing. No email or webhook transport is enabled."""

import argparse
import json
import sys

from sqlalchemy import func, select

from app.config import Settings
from app.db.database import Database
from app.db.models import OutboxDelivery
from app.outbox.worker import Worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--status", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    database = None
    try:
        settings = Settings()
        if settings.worker_database_url is None:
            raise ValueError("Configure ASSESSMENT_WORKER_DATABASE_URL first")
        database = Database(
            settings.model_copy(update={"database_url": settings.worker_database_url}), role="worker"
        )
        worker = Worker(
            database.sessions,
            lease_seconds=settings.outbox_lease_seconds,
            retry_base=settings.outbox_retry_base_seconds,
        )
        if args.once:
            print(json.dumps({"processed": worker.run_once(args.limit)}, sort_keys=True))
        with database.sessions() as session:
            counts = dict(
                session.execute(
                    select(OutboxDelivery.status, func.count()).group_by(OutboxDelivery.status)
                ).all()
            )
        print(
            json.dumps(
                {
                    "queue": {
                        status: counts.get(status, 0)
                        for status in ["pending", "processing", "delivered", "dead"]
                    }
                },
                sort_keys=True,
            )
        )
        if counts.get("dead", 0):
            raise SystemExit(2)
    except ValueError as error:
        print("WORKER=FAILED: " + str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print("WORKER=FAILED: check migration, worker grants and database availability", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    main()
