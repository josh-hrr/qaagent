"""Encryption for third-party credentials at rest.

A Linear API key or an Azure DevOps PAT is a live credential for a *different*
system. Storing it in plaintext means a database leak hands an attacker your
repositories and your ticket tracker, not just this app.

Deliberately keyed on ``CREDENTIAL_ENCRYPTION_KEY`` rather than ``SECRET_KEY``:
rotating ``SECRET_KEY`` is the break-glass that invalidates every session, and
that must not also render every stored credential unreadable.
"""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# Fixed key for development only, so a fresh clone runs with no setup. Anything
# encrypted with it is readable by anyone holding this source file.
#
# Must decode to EXACTLY 32 bytes or Fernet refuses it — this is checked by
# CryptoDevFallbackTests, which forces DEBUG=True because the test runner
# otherwise sets DEBUG=False and never reaches this branch.
DEV_KEY = "ZGV2LW9ubHktaW5zZWN1cmUta2V5LTMyLWJ5dGVzISE="  # b"dev-only-insecure-key-32-bytes!!"


class CredentialDecryptionError(Exception):
    """Ciphertext could not be read — usually a rotated or mismatched key."""


def generate_key() -> str:
    """A new key, as the base64 text that belongs in the environment."""
    return Fernet.generate_key().decode()


def _fernet() -> Fernet:
    key = getattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "") or ""
    if not key:
        if not settings.DEBUG:
            raise ImproperlyConfigured(
                "CREDENTIAL_ENCRYPTION_KEY must be set outside development. "
                "Generate one with: python manage.py generate_encryption_key"
            )
        key = DEV_KEY
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(
            "CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key. "
            "Generate one with: python manage.py generate_encryption_key"
        ) from exc


def encrypt(value: str) -> str:
    """Encrypt a credential. Returns base64 text safe for a TextField."""
    if not value:
        raise ValueError("Refusing to encrypt an empty credential.")
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a credential stored by :func:`encrypt`."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise CredentialDecryptionError(
            "Stored credential could not be decrypted. The encryption key has "
            "probably changed — reconnect the integration to store a fresh one."
        ) from exc


def hint_for(value: str) -> str:
    """A non-reversible display stub, e.g. ``lin_api_...7Kd2``.

    Enough for a human to recognise which key is installed, useless to an
    attacker. Never return the credential itself to a client.
    """
    tail = value[-4:] if len(value) >= 4 else "?" * len(value)
    prefix = value[:8] if value.startswith("lin_api_") else ""
    return f"{prefix}...{tail}"


def random_key_material(length: int = 32) -> str:
    """Base64 random bytes. Used by tests and the key-generation command."""
    return base64.urlsafe_b64encode(os.urandom(length)).decode()
