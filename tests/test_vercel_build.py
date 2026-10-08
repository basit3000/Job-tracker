"""Exercise hosted imports without loading local secrets or live services."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_startup_check(**overrides):
    # Inherit operating-system paths only, not developer credentials/config.
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper()
        in {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "PATHEXT",
        }
    }
    environment.update(
        PYTHON_DOTENV_DISABLED="1",
        VERCEL="1",
        SECRET_KEY="test-signing-key-with-at-least-32-characters",
        DATABASE_URL="postgresql://test:test@db.invalid/tracker",
        RATELIMIT_STORAGE_URI="rediss://redis.invalid/0",
        APP_BASE_URL="https://tracker.example.com",
        UPLOAD_STORAGE="s3",
        S3_BUCKET="private-test-resumes",
    )
    environment.update(overrides)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from ops.build_vercel import validate_startup; "
            "validate_startup()",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_missing_database_fails_before_deployment():
    result = run_startup_check(DATABASE_URL="")
    assert result.returncode != 0
    assert "Set DATABASE_URL to a durable PostgreSQL database" in result.stderr
    assert "Traceback" not in result.stderr


def test_valid_configuration_does_not_connect_to_services():
    result = run_startup_check()
    assert result.returncode == 0, result.stderr
    assert "Flask startup verified" in result.stdout


def test_invalid_signing_key_reports_name_without_value():
    result = run_startup_check(SECRET_KEY="private-short-key")
    assert result.returncode != 0
    assert "Set SECRET_KEY" in result.stderr
    assert "private-short-key" not in result.stderr
    assert "Traceback" not in result.stderr


def test_unexpected_startup_exception_does_not_echo_credentials():
    result = run_startup_check(
        DATABASE_URL="postgresql+missing://test:private-password@db.invalid/db"
    )
    assert result.returncode != 0
    assert "Flask startup check failed (NoSuchModuleError)" in result.stderr
    assert "private-password" not in result.stderr
    assert "db.invalid" not in result.stderr
    assert "Traceback" not in result.stderr


def test_vercel_runs_the_startup_check_and_static_build():
    config = json.loads((ROOT / "vercel.json").read_text())
    assert config["buildCommand"] == "python ops/build_vercel.py"
