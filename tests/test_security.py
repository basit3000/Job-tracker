import pytest

from app.utils import is_safe_redirect


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example",
        "//evil.example",
        "///evil.example",
        "/\\evil.example",
        "/jobs\n",
        "/\tevil.example",
        "jobs",
        "",
    ],
)
def test_rejects_unsafe_redirects(target):
    assert not is_safe_redirect(target)


@pytest.mark.parametrize(
    "target", ["/jobs", "/jobs?q=developer", "/dashboard#recent"]
)
def test_allows_local_redirects(target):
    assert is_safe_redirect(target)


def test_security_headers(client):
    response = client.get("/login")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store, private"
    assert (
        "script-src 'self' https://cdn.jsdelivr.net;"
        in response.headers["Content-Security-Policy"]
    )
