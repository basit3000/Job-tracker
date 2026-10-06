"""URL checks shared by input validation and rendering."""

from urllib.parse import urlsplit


def _has_unsafe_characters(value):
    return "\\" in value or any(
        ord(char) < 32 or ord(char) == 127 for char in value
    )


def is_safe_redirect(target):
    """Allow local absolute paths without browser URL-normalization tricks."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return False
    if _has_unsafe_characters(target):
        return False
    try:
        parsed = urlsplit(target)
    except ValueError:
        return False
    return not parsed.scheme and not parsed.netloc


def is_http_url(value):
    """Reject executable schemes and malformed URLs."""
    if not value or _has_unsafe_characters(value):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme.lower() in {"http", "https"}
            and bool(parsed.hostname)
            and (parsed.port is None or 0 < parsed.port <= 65535)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False
