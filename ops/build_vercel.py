"""Publish public static assets to Vercel's CDN directory."""

from pathlib import Path
from shutil import copyfile

ROOT = Path(__file__).resolve().parents[1]


def build_static(root=ROOT):
    source = root / "app" / "static"
    target = root / "public" / "static"
    # Enumerate the source only: uploads, databases and environment files are
    # never copied. Do not follow links out of the static directory.
    for path in source.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        if source.resolve() not in path.resolve().parents:
            continue
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        copyfile(path, destination)


if __name__ == "__main__":
    build_static()
