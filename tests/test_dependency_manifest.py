"""Prevent hosted builds and container installs from getting different pins."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hosted_runtime_dependencies_match_container_requirements():
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text())
    requirements = {
        line.strip()
        for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert set(manifest["project"]["dependencies"]) == requirements
