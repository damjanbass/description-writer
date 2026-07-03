"""Tests for connector credential encryption, model, and admin form."""
from __future__ import annotations

import os
from unittest import mock

from cryptography.fernet import Fernet
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import TestCase, override_settings

from .admin import ConnectorCredentialForm
from .crypto import (
    CredentialDecryptionError,
    decrypt_str,
    encrypt_str,
    get_fernet,
)
from .models import ConnectorCredential

# Two distinct, valid Fernet keys for round-trip / rotation tests.
_KEY_A = Fernet.generate_key().decode("ascii")
_KEY_B = Fernet.generate_key().decode("ascii")


def _make_org(name="Acme", slug="acme"):
    """Create an accounts.Organization via the app registry.

    Referenced only as a string FK in the model; the accounts app is built in
    parallel. name/slug is the expected create() shape.
    """
    Organization = apps.get_model("accounts", "Organization")
    return Organization.objects.create(name=name, slug=slug)


class CryptoRoundTripTests(TestCase):
    def test_encrypt_decrypt_round_trip(self):
        with mock.patch.dict(os.environ, {"KORPUS_FERNET_KEY": _KEY_A}):
            token = encrypt_str("s3cr3t-value")
            self.assertNotEqual(token, "s3cr3t-value")
            self.assertEqual(decrypt_str(token), "s3cr3t-value")

    def test_decrypt_with_different_key_raises_domain_error(self):
        with mock.patch.dict(os.environ, {"KORPUS_FERNET_KEY": _KEY_A}):
            token = encrypt_str("s3cr3t-value")
        # Rotate the key: the old token must no longer decrypt.
        with mock.patch.dict(os.environ, {"KORPUS_FERNET_KEY": _KEY_B}):
            with self.assertRaises(CredentialDecryptionError) as ctx:
                decrypt_str(token)
        # The error message must never leak the offending token.
        self.assertNotIn(token, str(ctx.exception))


class GetFernetKeyResolutionTests(TestCase):
    @override_settings(DEBUG=False)
    def test_missing_key_not_debug_raises(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KORPUS_FERNET_KEY", None)
            with self.assertRaises(ImproperlyConfigured):
                get_fernet()

    @override_settings(DEBUG=True)
    def test_missing_key_debug_derives_deterministic_key(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KORPUS_FERNET_KEY", None)
            # Deterministic across calls: a token from one call decrypts on
            # the next, which only holds if the derived key is stable.
            token = encrypt_str("dev-value")
            self.assertEqual(decrypt_str(token), "dev-value")


@override_settings(DEBUG=True)
class ConnectorCredentialModelTests(TestCase):
    def setUp(self):
        self.org = _make_org()

    def test_set_consumer_key_stores_ciphertext(self):
        cred = ConnectorCredential(
            organization=self.org,
            connector_type=ConnectorCredential.ConnectorType.WOOCOMMERCE,
            label="Prodavnica RS",
            base_url="https://shop.example.com",
        )
        cred.set_consumer_key("ck_plaintext")
        self.assertNotEqual(cred.key_encrypted, "ck_plaintext")
        self.assertNotIn("ck_plaintext", cred.key_encrypted)
        self.assertEqual(cred.consumer_key, "ck_plaintext")

    def test_consumer_secret_round_trip_and_blank(self):
        cred = ConnectorCredential(
            organization=self.org,
            connector_type=ConnectorCredential.ConnectorType.WOOCOMMERCE,
            label="Prodavnica RS",
            base_url="https://shop.example.com",
        )
        self.assertEqual(cred.consumer_secret, "")
        cred.set_consumer_secret("cs_plaintext")
        self.assertEqual(cred.consumer_secret, "cs_plaintext")

    def test_str_contains_no_secret(self):
        cred = ConnectorCredential(
            organization=self.org,
            connector_type=ConnectorCredential.ConnectorType.WOOCOMMERCE,
            label="Prodavnica RS",
            base_url="https://shop.example.com",
        )
        cred.set_consumer_key("ck_supersecret")
        rendered = str(cred)
        self.assertIn("Prodavnica RS", rendered)
        self.assertNotIn("ck_supersecret", rendered)
        self.assertNotIn(cred.key_encrypted, rendered)

    def _clean_with_url(self, url):
        cred = ConnectorCredential(
            organization=self.org,
            connector_type=ConnectorCredential.ConnectorType.WOOCOMMERCE,
            label="Prodavnica RS",
            base_url=url,
        )
        cred.set_consumer_key("ck")
        cred.full_clean()

    def test_http_non_localhost_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self._clean_with_url("http://shop.example.com")
        self.assertIn("base_url", ctx.exception.message_dict)

    def test_https_ok(self):
        self._clean_with_url("https://shop.example.com")

    def test_http_localhost_ok(self):
        self._clean_with_url("http://localhost:8000")

    def test_userinfo_in_url_rejected(self):
        # https://key:secret@host would put credential material into
        # connector exception strings persisted to publish_error/AuditLog.
        with self.assertRaises(ValidationError) as ctx:
            self._clean_with_url("https://ck_key:cs_secret@shop.example.com")
        self.assertIn("base_url", ctx.exception.message_dict)


@override_settings(DEBUG=True)
class ConnectorCredentialAdminFormTests(TestCase):
    def setUp(self):
        self.org = _make_org()
        self.cred = ConnectorCredential(
            organization=self.org,
            connector_type=ConnectorCredential.ConnectorType.WOOCOMMERCE,
            label="Prodavnica RS",
            base_url="https://shop.example.com",
        )
        self.cred.set_consumer_key("ck_plaintext_secret")
        self.cred.save()

    def test_change_form_html_leaks_no_credential(self):
        form = ConnectorCredentialForm(instance=self.cred)
        html = form.as_p()
        self.assertNotIn("ck_plaintext_secret", html)
        self.assertNotIn(self.cred.key_encrypted, html)
        # PasswordInput must not echo any value attribute back.
        self.assertNotIn("render_value", html)  # sanity: not a leaked attr

    def test_blank_password_keeps_existing_credential(self):
        original = self.cred.key_encrypted
        form = ConnectorCredentialForm(
            data={
                "organization": self.org.pk,
                "connector_type": ConnectorCredential.ConnectorType.WOOCOMMERCE,
                "label": "Prodavnica RS",
                "base_url": "https://shop.example.com",
                "consumer_key": "",
                "consumer_secret": "",
            },
            instance=self.cred,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.key_encrypted, original)
        self.assertEqual(saved.consumer_key, "ck_plaintext_secret")

    def test_new_value_reencrypts_credential(self):
        original = self.cred.key_encrypted
        form = ConnectorCredentialForm(
            data={
                "organization": self.org.pk,
                "connector_type": ConnectorCredential.ConnectorType.WOOCOMMERCE,
                "label": "Prodavnica RS",
                "base_url": "https://shop.example.com",
                "consumer_key": "ck_rotated",
                "consumer_secret": "",
            },
            instance=self.cred,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertNotEqual(saved.key_encrypted, original)
        self.assertEqual(saved.consumer_key, "ck_rotated")

    def test_add_form_requires_consumer_key(self):
        form = ConnectorCredentialForm(
            data={
                "organization": self.org.pk,
                "connector_type": ConnectorCredential.ConnectorType.WOOCOMMERCE,
                "label": "New Store",
                "base_url": "https://new.example.com",
                "consumer_key": "",
                "consumer_secret": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("consumer_key", form.errors)
