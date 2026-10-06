"""Migrate separately, then serve with the runtime database role."""

import os
import subprocess


def main():
    environment = os.environ.copy()
    migration_url = environment.get("MIGRATION_DATABASE_URL")
    if migration_url:
        environment["DATABASE_URL"] = migration_url
    subprocess.run(
        ["flask", "--app", "run.py", "db", "upgrade"],
        env=environment,
        check=True,
    )
    if migration_url:
        subprocess.run(
            ["flask", "--app", "run.py", "grant-runtime"],
            env=environment,
            check=True,
        )
    # The Gunicorn workers must not inherit schema-owner credentials.
    os.environ.pop("MIGRATION_DATABASE_URL", None)
    os.execvp(
        "gunicorn",
        ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "3", "run:app"],
    )


if __name__ == "__main__":
    main()
