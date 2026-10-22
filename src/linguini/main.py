"""ASGI entrypoint used by ``fastapi run --entrypoint linguini.main:app``."""

from linguini.app import create_app

app = create_app()
