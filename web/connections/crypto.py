"""Symmetric encryption of connector credentials at rest.

Connector credentials (WooCommerce consumer key/secret and friends) are
stored encrypted in the database so a database dump alone never exposes a
customer's store credentials. Encryption uses Fernet (AES-128-CBC +
HMAC-SHA256, authenticated), keyed by a single symmetric key held outside
the database in the ``KORPUS_FERNET_KEY`` environment variable.

Key management contract:

  - Production MUST set ``KORPUS_FERNET_KEY`` to a standard urlsafe-base64
    32-byte Fernet key. Generate one with::

        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

  - In DEBUG (local development) only, if the env var is unset we derive a
    stable throwaway key from ``SECRET_KEY`` so the app runs out of the box.
    This is DEV ONLY and never happens when ``DEBUG`` is false.

Key rotation: rotating ``KORPUS_FERNET_KEY`` makes every previously stored
ciphertext undecryptable — :func:`decrypt_str` surfaces that as a clear
:class:`CredentialDecryptionError` rather than a bare cryptography error.
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_GENERATE_HINT = (
    'python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"'
)


class CredentialDecryptionError(Exception):
    """Raised when a stored credential token cannot be decrypted.

    The most common cause is that ``KORPUS_FERNET_KEY`` has changed (been
    rotated) since the token was written, or the ciphertext was corrupted.
    The message deliberately never includes the offending token.
    """


def _derive_dev_key() -> bytes:
    """Derive a stable, DEV-ONLY Fernet key from ``SECRET_KEY``.

    A Fernet key is urlsafe-base64 of exactly 32 bytes; sha256 conveniently
    yields 32 bytes, so we hash SECRET_KEY and base64-encode the digest. This
    is deterministic (same key every call/process for a given SECRET_KEY) so
    dev data round-trips across restarts. NEVER used when DEBUG is false.
    """
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet() -> Fernet:
    """Return a configured :class:`Fernet` instance.

    Key resolution:
      - ``KORPUS_FERNET_KEY`` from the environment if set.
      - Otherwise, in DEBUG only, a derived dev-only key (see
        :func:`_derive_dev_key`).
      - Otherwise (not DEBUG, unset) raise :class:`ImproperlyConfigured`.
    """
    key = os.environ.get("KORPUS_FERNET_KEY")
    if key:
        return Fernet(key.encode("ascii") if isinstance(key, str) else key)

    if settings.DEBUG:
        return Fernet(_derive_dev_key())

    raise ImproperlyConfigured(
        "KORPUS_FERNET_KEY environment variable is required to encrypt "
        "connector credentials. Generate one with: " + _GENERATE_HINT
    )


def encrypt_str(plaintext: str) -> str:
    """Encrypt a unicode string, returning an ascii Fernet token."""
    token = get_fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_str(token: str) -> str:
    """Decrypt a Fernet token back to the original string.

    Raises :class:`CredentialDecryptionError` (never leaking the token) if
    the token is invalid — typically a rotated/wrong ``KORPUS_FERNET_KEY``.
    """
    try:
        plaintext = get_fernet().decrypt(token.encode("ascii"))
    except InvalidToken as exc:
        raise CredentialDecryptionError(
            "Could not decrypt a stored connector credential. The encryption "
            "key (KORPUS_FERNET_KEY) may have changed since it was saved, or "
            "the stored value is corrupted."
        ) from exc
    return plaintext.decode("utf-8")
