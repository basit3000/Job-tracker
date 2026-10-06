import pytest

from config import env_bool, normalize_database_url


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_postgresql_urls_keep_connection_details(scheme):
    details = "user:test-password@db:5432/jobtracker?sslmode=require"
    assert normalize_database_url(f"{scheme}://{details}") == (
        f"postgresql+psycopg2://{details}"
    )


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///jobtracker.db",
        "postgresql+psycopg2://db/jobtracker",
        "postgresql+psycopg://db/jobtracker",
    ],
)
def test_explicit_database_drivers_are_preserved(url):
    assert normalize_database_url(url) == url


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("TRUE", True),
        ("false", False),
        ("", False),
    ],
)
def test_environment_boolean_conventions(monkeypatch, value, expected):
    monkeypatch.setenv("TEST_BOOL", value)
    assert env_bool("TEST_BOOL") is expected
