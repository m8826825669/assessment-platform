"""ASM-01/PUB-01/SCH-01 coordinator browser gate on disposable restricted PostgreSQL."""

import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

import uvicorn
from sqlalchemy import text
from test_question_review import EXAMPLES, approve, context, path, prepare, submit
from test_question_taxonomy import term

from app.db.models import Membership


def test_real_coordinator_exam_journeys(security_database):
    db = security_database
    db.client.app.state.settings = db.settings.model_copy(
        update={"login_account_limit": 100, "login_ip_limit": 200}
    )
    author, reviewer, _ = prepare(db)
    taxonomy = term(db, author, code="browser_exam", label="Browser grammar")
    for index in (1, 2):
        created = db.client.post(
            path(db),
            headers=author,
            json={
                "title": f"Assembly question {index}",
                "content": EXAMPLES[0],
                "taxonomy_ids": [taxonomy["id"]],
            },
        )
        assert created.status_code == 201, created.text
        approve(db, reviewer, submit(db, author, created.json()))
    with db.admin_engine.begin() as connection:
        context(connection, db, tenant="b")
        connection.execute(
            Membership.__table__.insert().values(
                id=uuid4(), tenant_id=db.ids["tenant_b"], user_id=db.ids["candidate"], role="coordinator"
            )
        )
    root = Path(__file__).resolve().parents[2]
    npm = shutil.which("npm")
    assert npm and (root / "frontend/node_modules/next").is_dir(), "Run npm ci in frontend first"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    server = uvicorn.Server(
        uvicorn.Config(db.client.app, log_level="warning", access_log=False, lifespan="off")
    )
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ASSESSMENT_") and key not in {"DATABASE_URL", "MIGRATION_URL"}
    }
    environment.update(
        ASSESSMENT_API_ORIGIN=f"http://127.0.0.1:{listener.getsockname()[1]}",
        ASSESSMENT_BROWSER_PASSWORD=db.password,
        ASSESSMENT_BROWSER_TENANT=str(db.ids["tenant_a"]),
        ASSESSMENT_BROWSER_OTHER_TENANT=str(db.ids["tenant_b"]),
        ASSESSMENT_BROWSER_TAXONOMY=taxonomy["id"],
        ASSESSMENT_COORDINATOR_BROWSER_GATE="1",
        ASSESSMENT_BROWSER_EXECUTABLE=os.environ.get("ASSESSMENT_BROWSER_EXECUTABLE", ""),
        NEXT_TELEMETRY_DISABLED="1",
    )
    try:
        deadline = time.monotonic() + 20
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.1)
        assert server.started, "Isolated coordinator browser API did not start"
        result = subprocess.run(
            [npm, "run", "test:browser", "--", "exams.spec.ts"],
            cwd=root / "frontend",
            env=environment,
            check=False,
        )
        assert result.returncode == 0, "Coordinator browser gate failed; inspect Playwright output"
        with db.admin_engine.begin() as connection:
            context(connection, db)
            for table, action, count in [
                ("exam_blueprint_drafts", "exam.draft_created", 2),
                ("exam_publications", "exam.published", 1),
                ("exam_sittings", "exam.sitting_created", 1),
            ]:
                expected_rows = 4 if table == "exam_blueprint_drafts" else count
                assert connection.scalar(text("SELECT count(*) FROM " + table)) == expected_rows
                assert (
                    connection.scalar(
                        text("SELECT count(*) FROM audit_records WHERE action=:action"), {"action": action}
                    )
                    == count
                )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM audit_records WHERE action='exam.draft_revised'")
                )
                == 2
            )
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
