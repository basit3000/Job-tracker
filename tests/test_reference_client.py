"""Real HTTP pairing, Node retries, conflicts and revocation."""

import http.cookiejar
import re
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from werkzeug.serving import WSGIRequestHandler, make_server

from app.models import (
    ApplicationMapping,
    ChangeEntry,
    Device,
    JobApplication,
    MutationReceipt,
)


class QuietHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        pass


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is unavailable")
def test_real_reference_client_pairs_retries_conflicts_and_revokes(
    app, users, tmp_path
):
    server = make_server(
        "127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    script = (
        Path(__file__).resolve().parents[1]
        / "reference-client"
        / "integration.mjs"
    )
    state = tmp_path / "private" / "client.json"
    process = subprocess.Popen(
        ["node", str(script), origin, str(state)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = process.stdout.readline().strip()
        assert line.startswith("PAIRING_CODE:")
        code = line.split(":", 1)[1]
        browser = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

        def csrf(path):
            with browser.open(origin + path, timeout=5) as response:
                match = re.search(
                    rb'name="csrf_token"[^>]*value="([^"]+)"', response.read()
                )
                assert match
                return match.group(1).decode()

        login = urllib.parse.urlencode(
            {
                "email": "owner@example.com",
                "password": "correct-password",
                "csrf_token": csrf("/login"),
            }
        ).encode()
        browser.open(origin + "/login", data=login, timeout=5).close()
        approval = urllib.parse.urlencode(
            {
                "code": code,
                "action": "approve",
                "csrf_token": csrf("/integrations"),
            }
        ).encode()
        browser.open(
            origin + "/integrations", data=approval, timeout=5
        ).close()
        stdout, stderr = process.communicate(timeout=40)
        assert process.returncode == 0, stderr
        assert "REFERENCE_CLIENT_OK" in stdout
        with app.app_context():
            assert JobApplication.query.count() == 1
            assert JobApplication.query.one().deleted_at
            assert ApplicationMapping.query.count() == 1
            assert MutationReceipt.query.count() == 4
            assert ChangeEntry.query.count() == 4
            assert Device.query.one().revoked_at
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
