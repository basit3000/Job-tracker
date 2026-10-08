"""Release-phase migrations, without touching the runtime upload volume."""

import os
import subprocess
import sys
from tempfile import TemporaryDirectory


def main():
    environment = os.environ.copy()
    migration_url = environment.get("MIGRATION_DATABASE_URL")
    if migration_url:
        environment["DATABASE_URL"] = migration_url
    with TemporaryDirectory(prefix="jobtracker-migrate-") as upload_folder:
        # Railway does not mount volumes during pre-deploy commands.
        environment["UPLOAD_FOLDER"] = upload_folder
        command = [sys.executable, "-m", "flask", "--app", "run.py"]
        subprocess.run(
            [*command, "db", "upgrade"],
            env=environment,
            check=True,
        )
        if environment.get("GRANT_RUNTIME_ROLE", "false").lower() == "true":
            subprocess.run(
                [*command, "grant-runtime"],
                env=environment,
                check=True,
            )


if __name__ == "__main__":
    main()
