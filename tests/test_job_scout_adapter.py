"""Test the adjacent Job Scout adapter with a disposable tracker account."""

import http.cookiejar
import os
import re
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.models import ApplicationMapping, Device, JobApplication
from tests.test_reference_client import QuietHandler

SCOUT_ROOT = Path(
    os.environ.get(
        "JOB_SCOUT_ROOT", Path(__file__).resolve().parents[2] / "job-scout"
    )
)
SCRIPT = SCOUT_ROOT / "scripts/test-helpers/cloud-tracker-integration.mjs"


@pytest.mark.skipif(
    shutil.which("node") is None or not SCRIPT.is_file(),
    reason="Node and Job Scout adapter checkout are required",
)
def test_job_scout_adapter_pairs_previews_retries_imports_and_revokes(
    app, users, tmp_path
):
    server = make_server(
        "127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    process = subprocess.Popen(
        ["node", str(SCRIPT), origin, str(tmp_path / "scout")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = process.stdout.readline().strip()
        assert line.startswith("PAIRING_CODE:")
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

        def post(path, fields):
            fields["csrf_token"] = csrf(path)
            browser.open(
                origin + path,
                data=urllib.parse.urlencode(fields).encode(),
                timeout=5,
            ).close()

        post("/login", {
            "email": "owner@example.com", "password": "correct-password"
        })
        post("/integrations", {
            "code": line.split(":", 1)[1], "action": "approve"
        })
        stdout, stderr = process.communicate(timeout=60)
        assert process.returncode == 0, stderr
        assert "JOB_SCOUT_ADAPTER_OK" in stdout
        with app.app_context():
            assert JobApplication.query.count() == 2
            assert ApplicationMapping.query.count() == 2
            assert Device.query.one().revoked_at
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
