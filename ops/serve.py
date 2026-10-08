"""Container startup with platform ports and optional release migrations."""

import argparse
import os
import subprocess
import sys


def _positive_integer(name, default, maximum):
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        raise ValueError(f"{name} must be a positive integer.") from None
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}.")
    return str(value)


def main(*, skip_migrations=False):
    port = _positive_integer("PORT", "5000", 65535)
    workers = _positive_integer("WEB_CONCURRENCY", "3", 32)
    if not skip_migrations:
        subprocess.run([sys.executable, "ops/migrate.py"], check=True)
    environment = os.environ.copy()
    environment.pop("MIGRATION_DATABASE_URL", None)
    # Prevent dotenv from reintroducing schema-owner credentials in workers.
    environment["PYTHON_DOTENV_DISABLED"] = "1"
    os.execvpe(
        "gunicorn",
        [
            "gunicorn",
            "--bind",
            f"0.0.0.0:{port}",
            "--workers",
            workers,
            "--timeout",
            "120",
            "wsgi:app",
        ],
        environment,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-migrations", action="store_true")
    main(skip_migrations=parser.parse_args().skip_migrations)
