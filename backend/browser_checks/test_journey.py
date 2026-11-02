"""Full browser gate: real restricted PostgreSQL, real disposable storage and ClamAV."""

import base64
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
from sqlalchemy.orm import Session
from test_authoring_media import png
from test_question_review import prepare

from app.db.models import Membership, User
from app.identity.security import hash_password


def test_real_browser_journeys(live_media):
    db, _, _, _ = live_media
    db.client.app.state.settings = db.settings.model_copy(
        update={"login_account_limit": 100, "login_ip_limit": 200}
    )
    prepare(db)  # outsider reviewer, candidate coordinator, admin_a remains administrator.
    with Session(db.admin_engine) as session, session.begin():
        session.execute(text("SELECT set_config('app.tenant_id',:id,true)"), {"id": str(db.ids["tenant_a"])})
        user = User(
            id=uuid4(),
            email="browser_author@example.test",
            display_name="Browser author",
            password_hash=hash_password(db.password),
        )
        session.add(user)
        session.flush()
        session.add(Membership(tenant_id=db.ids["tenant_a"], user_id=user.id, role="author"))
    root = Path(__file__).resolve().parents[2]
    npm = shutil.which("npm")
    assert npm, "Node/npm is required for the separate browser gate"
    assert (root / "frontend/node_modules/next").is_dir(), "Run npm ci in frontend first"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
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
        ASSESSMENT_API_ORIGIN=f"http://127.0.0.1:{port}",
        ASSESSMENT_BROWSER_PASSWORD=db.password,
        ASSESSMENT_BROWSER_TENANT=str(db.ids["tenant_a"]),
        ASSESSMENT_BROWSER_GATE="1",
        ASSESSMENT_BROWSER_PNG=base64.b64encode(png()).decode(),
        NEXT_TELEMETRY_DISABLED="1",
    )
    try:
        deadline = time.monotonic() + 20
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.1)
        assert server.started, "Isolated browser API did not start"
        result = subprocess.run(
            [npm, "run", "test:browser"], cwd=root / "frontend", env=environment, check=False
        )
        assert result.returncode == 0, "Real browser gate failed; inspect Playwright output"
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
