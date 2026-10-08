"""Resume storage and the configured upload policy."""

from pathlib import Path
from uuid import uuid4

from flask import current_app


def upload_size_label():
    """Describe the configured request limit for forms and error pages."""
    size = current_app.config["MAX_CONTENT_LENGTH"]
    if size is None:
        return "unlimited"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):g} MB"
    if size >= 1024:
        return f"{size / 1024:g} KB"
    return f"{size} bytes"


def resume_upload_help():
    extensions = sorted(current_app.config["ALLOWED_UPLOAD_EXTENSIONS"])
    return (
        f"{', '.join(ext.upper() for ext in extensions)} "
        f"(max {upload_size_label()})."
    )


def resume_path(filename):
    """Confine stored names and symlinks to the upload directory."""
    if not filename or "\\" in filename or Path(filename).name != filename:
        return None
    try:
        root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
        path = (root / filename).resolve()
    except (OSError, ValueError):
        return None
    return path if path.parent == root else None


def delete_resume(filename):
    if not filename:
        return
    path = resume_path(filename)
    if path is None:
        current_app.logger.warning(
            "Refused to delete a resume outside the upload directory."
        )
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # Cleanup failure must not make a committed change appear to fail.
        # File exceptions include private paths; record only the failure.
        current_app.logger.warning("Could not remove a retired resume file.")


def save_resume(file_storage):
    extension = file_storage.filename.rsplit(".", 1)[-1].lower()
    if extension not in current_app.config["ALLOWED_UPLOAD_EXTENSIONS"]:
        raise ValueError("Unsupported resume extension.")
    name = f"{uuid4().hex}.{extension}"
    path = resume_path(name)
    if path is None:
        raise ValueError("Invalid resume storage path.")
    created = False
    try:
        with path.open("xb") as destination:
            created = True
            file_storage.save(destination)
    except Exception:
        if created:
            delete_resume(name)
        raise
    return name
