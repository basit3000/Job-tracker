"""Resume storage and the configured upload policy."""

from pathlib import Path
from uuid import uuid4

from flask import abort, current_app, send_from_directory


def valid_resume_name(filename):
    # Names are opaque basenames, never S3 prefixes or response headers.
    return bool(
        filename
        and filename not in {".", ".."}
        and all(
            character.isascii() and (character.isalnum() or character in "._-")
            for character in filename
        )
    )


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
    if not valid_resume_name(filename):
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
    if current_app.config["UPLOAD_STORAGE"] == "s3":
        from app.object_storage import delete_object

        if valid_resume_name(filename):
            delete_object(filename)
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
    if current_app.config["UPLOAD_STORAGE"] == "s3":
        from app.object_storage import save_object

        save_object(name, file_storage.stream)
        return name
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


def download_resume(filename):
    if not valid_resume_name(filename):
        abort(404)
    if current_app.config["UPLOAD_STORAGE"] == "s3":
        from app.object_storage import download_object

        return download_object(filename)
    if resume_path(filename) is None:
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        filename,
        as_attachment=True,
    )
