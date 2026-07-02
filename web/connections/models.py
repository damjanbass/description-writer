"""Per-organization connector credentials, encrypted at rest.

A :class:`ConnectorCredential` binds one set of store API credentials (e.g. a
WooCommerce consumer key/secret) to an :class:`accounts.Organization`. The
secret material is never stored in the clear: :func:`connections.crypto`
Fernet-encrypts it, and only the ciphertext lives in the database columns.
The plaintext is available only transiently via the ``consumer_key`` /
``consumer_secret`` properties, which decrypt on access.
"""
from __future__ import annotations

from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.db import models

from .crypto import decrypt_str, encrypt_str

# Hostnames for which plain http is tolerated (dev convenience). Mirrors the
# rule enforced in the engine's connectors/woocommerce.py: credentials travel
# in an Authorization header, so any non-local host must use https.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


class ConnectorCredential(models.Model):
    """API credentials for one store connector, owned by an organization."""

    class ConnectorType(models.TextChoices):
        WOOCOMMERCE = "woocommerce", "WooCommerce"
        SELLTICO = "selltico", "Selltico"
        TAU_COMMERCE = "tau_commerce", "TAU Commerce"

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="connector_credentials",
    )
    connector_type = models.CharField(
        max_length=32,
        choices=ConnectorType.choices,
    )
    label = models.CharField(
        max_length=100,
        help_text='Human label for this store, e.g. "Prodavnica RS".',
    )
    base_url = models.URLField(
        help_text="Store base URL. Must use https (http allowed only for "
        "localhost/127.0.0.1).",
    )
    # Fernet ciphertext only — never the plaintext credential. `secret` is
    # blank-able because not every connector uses a separate secret.
    key_encrypted = models.TextField()
    secret_encrypted = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("organization", "label")

    def __str__(self) -> str:
        # NEVER include credential material (plaintext or ciphertext) here.
        return f"{self.label} ({self.get_connector_type_display()})"

    def __repr__(self) -> str:
        return f"<ConnectorCredential {self.label!r} {self.connector_type!r}>"

    # -- credential accessors -------------------------------------------------
    # Writers encrypt-and-store; readers decrypt on access. This keeps the
    # plaintext out of the model's persisted state entirely.
    def set_consumer_key(self, raw: str) -> None:
        """Encrypt and store the consumer key."""
        self.key_encrypted = encrypt_str(raw)

    def set_consumer_secret(self, raw: str) -> None:
        """Encrypt and store the consumer secret."""
        self.secret_encrypted = encrypt_str(raw)

    @property
    def consumer_key(self) -> str:
        """Decrypt and return the consumer key (may raise on key rotation)."""
        return decrypt_str(self.key_encrypted)

    @property
    def consumer_secret(self) -> str:
        """Decrypt and return the consumer secret, or "" if none is stored."""
        if not self.secret_encrypted:
            return ""
        return decrypt_str(self.secret_encrypted)

    # -- validation -----------------------------------------------------------
    def clean(self) -> None:
        """Enforce the https-except-localhost transport rule on base_url.

        Mirrors connectors/woocommerce.py: credentials ship in an
        Authorization header, so a non-HTTPS transport to a remote host would
        leak them. Plain http is allowed only for localhost/127.0.0.1.
        """
        super().clean()
        if not self.base_url:
            return
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" and (
            parsed.scheme != "http" or parsed.hostname not in _LOCAL_HOSTS
        ):
            raise ValidationError(
                {
                    "base_url": (
                        "base_url must use https (http is allowed only for "
                        "localhost/127.0.0.1)."
                    )
                }
            )
