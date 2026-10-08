"""Check Flask startup before publishing public static assets to Vercel."""

import sys
from pathlib import Path
from shutil import copyfile

ROOT = Path(__file__).resolve().parents[1]


def validate_startup():
    # Executing a file in ops/ otherwise places only ops/ on the import path.
    sys.path.insert(0, str(ROOT))
    try:
        from app.deployment import DeploymentConfigurationError

        try:
            from wsgi import app
        except DeploymentConfigurationError as error:
            raise SystemExit(
                f"Deployment configuration error: {error}"
            ) from None
    except Exception as error:
        # Invalid URLs and provider exceptions can contain secret values.
        raise SystemExit(
            f"Flask startup check failed ({type(error).__name__}). "
            "Check runtime dependencies and environment variable formats."
        ) from None
    if not callable(app):
        raise SystemExit("The WSGI entrypoint must expose a callable app.")
    print("Flask startup verified; connectivity is checked separately.")


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
    validate_startup()
    build_static()
