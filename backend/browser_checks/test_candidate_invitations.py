"""SCH-01/ACC-01 candidate journey against a disposable restricted PostgreSQL API."""

import os
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import uvicorn
from sqlalchemy import text
from test_exam_sittings import registration, sitting_setup
from test_question_review import context

from app.db.models import Membership


def test_real_candidate_invitation_journeys(security_database):
    db = security_database
    db.client.app.state.settings = db.settings.model_copy(
        update={"login_account_limit": 100, "login_ip_limit": 200}
    )
    setup = sitting_setup.__wrapped__(db)
    _, staff, _, candidates, original, body = setup
    ids = []
    for index in range(1, 15):
        identity = uuid4()
        url = original.rsplit("/", 1)[0] + "/" + str(identity)
        opening = datetime.fromisoformat(body["opens_at"]) + timedelta(days=index)
        response = db.client.put(
            url,
            headers=staff,
            json={
                **body,
                "title": f"Invitation {index:02}",
                "opens_at": opening.isoformat(),
                "closes_at": (opening + timedelta(hours=2)).isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        row = registration(candidates[0], extra=10)
        row["accommodation_reason"] = "PRIVATE_ACCOMMODATION_SENTINEL"
        response = db.client.post(url + "/registrations", headers=staff, json={"registrations": [row]})
        assert response.status_code == 200, response.text
        ids.append((url, row["id"]))
    # Separate candidates and tenants must never be filtered merely by the browser.
    other = registration(candidates[1])
    assert (
        db.client.post(
            ids[0][0] + "/registrations", headers=staff, json={"registrations": [other]}
        ).status_code
        == 200
    )
    with db.admin_engine.begin() as connection:
        context(connection, db, tenant="b")
        connection.execute(
            Membership.__table__.insert().values(
                id=uuid4(), tenant_id=db.ids["tenant_b"], user_id=candidates[0], role="candidate"
            )
        )
    # Terminal invitations and a later amended historical acknowledgement.
    response = db.client.put(
        ids[11][0] + "/cancellation", headers=staff, json={"reason_code": "administrative"}
    )
    assert response.status_code == 200, response.text
    response = db.client.put(
        ids[12][0] + "/registrations/" + ids[12][1] + "/changes/" + str(uuid4()),
        headers=staff,
        json={"action": "withdraw", "expected_revision": 1, "reason": "PRIVATE_WITHDRAWAL_SENTINEL"},
    )
    assert response.status_code == 200, response.text
    candidate_headers = db.login(candidates[0].hex)
    invitation = f"/api/v1/tenants/{db.ids['tenant_a']}/exam-invitations/{ids[13][1]}"
    assert db.client.post(invitation + "/accept", headers=candidate_headers).status_code == 200
    amendment = db.client.put(
        ids[13][0] + "/registrations/" + ids[13][1] + "/changes/" + str(uuid4()),
        headers=staff,
        json={
            "action": "amend_accommodation",
            "expected_revision": 1,
            "extra_minutes": 20,
            "reason": "PRIVATE_AMENDMENT_SENTINEL",
        },
    )
    assert amendment.status_code == 200, amendment.text
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
        ASSESSMENT_BROWSER_CANDIDATE=candidates[0].hex + "@example.test",
        ASSESSMENT_BROWSER_OTHER_CANDIDATE=candidates[1].hex + "@example.test",
        ASSESSMENT_BROWSER_TENANT=str(db.ids["tenant_a"]),
        ASSESSMENT_BROWSER_OTHER_TENANT=str(db.ids["tenant_b"]),
        ASSESSMENT_CANDIDATE_BROWSER_GATE="1",
        NEXT_TELEMETRY_DISABLED="1",
        ASSESSMENT_BROWSER_EXECUTABLE=os.environ.get("ASSESSMENT_BROWSER_EXECUTABLE", ""),
    )
    try:
        deadline = time.monotonic() + 20
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.1)
        assert server.started, "Isolated candidate browser API did not start"
        result = subprocess.run(
            [npm, "run", "test:browser", "--", "invitations.spec.ts"],
            cwd=root / "frontend",
            env=environment,
            check=False,
        )
        assert result.returncode == 0, "Candidate browser gate failed; inspect Playwright output"
        with db.admin_engine.begin() as connection:
            context(connection, db)
            receipts = connection.scalar(text("SELECT count(*) FROM registration_acceptances"))
            events = connection.scalar(
                text("SELECT count(*) FROM audit_records WHERE action='exam.invitation_accepted'")
            )
            assert receipts == events == 3  # seed + two acknowledgements; retry adds nothing.
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
