"""Consistent read-only SQLite backups, including committed WAL data."""

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path


def backup_database(source, destination):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).resolve()
    if source == destination or destination.suffix.lower() not in {
        ".db",
        ".sqlite",
        ".sqlite3",
    }:
        raise ValueError("Choose a separate ignored SQLite backup file.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600
    )
    os.close(descriptor)
    try:
        with (
            closing(
                sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
            ) as original,
            closing(sqlite3.connect(destination)) as backup,
        ):
            original.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup integrity check failed.")
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    backup_database(args.database, args.destination)
    print("SQLite backup completed and verified. Keep it private.")


if __name__ == "__main__":
    main()
