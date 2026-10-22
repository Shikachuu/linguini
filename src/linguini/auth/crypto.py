"""Symmetric encryption for third-party tokens stored in the database."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from linguini.config import Settings


def fernet(settings: Settings) -> Fernet:
    """Derive a Fernet from the instance secret.

    Returns:
        A Fernet bound to ``LINGUINI_SECRET_KEY``.
    """
    digest = hashlib.sha256(settings.secret_key.get_secret_value().encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(settings: Settings, value: str) -> str:
    """Encrypt a string for storage.

    Returns:
        The Fernet token.
    """
    return fernet(settings).encrypt(value.encode()).decode()


def decrypt(settings: Settings, token: str) -> str:
    """Decrypt a stored value.

    Returns:
        The plaintext.
    """
    return fernet(settings).decrypt(token.encode()).decode()
