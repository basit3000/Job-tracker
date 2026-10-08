"""Production WSGI entry point; never starts development background threads."""

from run import app

__all__ = ["app"]
