"""Guard the exclusion rules for local data and credentials."""

import shutil
import subprocess
from pathlib import Path

import pytest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PATHS = (
    ".env",
    ".env.production",
    "nested/.env",
    "settings.env",
    "jobtracker.db",
    "jobtracker.db-wal",
    "jobtracker.db-shm",
    "jobtracker.db-journal",
    "nested/jobs.sqlite3",
    "nested/jobs.sqlite3-wal",
    "export.sql",
    "export.sql.gz",
    "backup.dump",
    "backup.bak",
    "nested/export.sql",
    "nested/private/account.json",
    "private/reference-client.json",
    "private/reference-client.json.lock",
    "private/reference-client.json.temporary.tmp",
    "data/export.csv",
    "backups/database.zip",
    "database_backups/full.zip",
    "secrets/config.json",
    "credentials/service.json",
    "service-account.json",
    "client_secret_oauth.json",
    "server.key",
    "nested/certificate.pem",
    "id_rsa",
    "nested/id_ed25519",
    "server.pfx",
    "cache.rdb",
    "logs/app.log",
    "logs/app.log.1",
    "uploads/resume.pdf",
    "upload/resume.docx",
    "nested/uploads/resume.pdf",
    "nested/.venv/private.txt",
)
PUBLIC_PATHS = (
    "app/models.py",
    "app/routes/jobs.py",
    "app/templates/base.html",
    "app/static/js/forms.js",
    "config.py",
    "requirements.txt",
    "migrations/env.py",
    "migrations/versions/example_schema.py",
)


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is unavailable")
@pytest.mark.parametrize("ignore_file", [".gitignore", ".dockerignore"])
def test_private_file_globs_cover_root_and_nested_paths(tmp_path, ignore_file):
    # These exclusion files use the shared Git/Docker glob syntax. This
    # checks that subset with Git; it does not build a Docker image.
    subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    shutil.copyfile(ROOT / ignore_file, tmp_path / ".gitignore")
    candidates = PRIVATE_PATHS + PUBLIC_PATHS
    result = subprocess.run(
        ["git", "check-ignore", "--stdin", "-z"],
        cwd=tmp_path,
        input=("\0".join(candidates) + "\0").encode(),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert set(result.stdout.decode().rstrip("\0").split("\0")) == set(
        PRIVATE_PATHS
    )


def test_environment_example_contains_empty_credentials():
    example = dotenv_values(ROOT / ".env.example")
    assert example["SECRET_KEY"] == ""
    assert example["POSTGRES_PASSWORD"] == ""
    assert example["APP_DB_PASSWORD"] == ""
    assert example["MIGRATOR_DB_PASSWORD"] == ""
    assert example["GOOGLE_CLIENT_SECRET"] == ""
    assert example["GOOGLE_CLIENT_ID"] == ""


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is unavailable")
def test_environment_example_can_be_committed():
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", ".env.example"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
