"""Tests for batches.dbstorage.DatabaseStorage -- the Postgres-backed file
storage serverless deployments select as STORAGES["default"]
(config.settings.vercel).

The FieldTests go through the real `Batch.source_file` FileField under
override_settings(STORAGES=...): Django resets its storage handler (and the
default_storage lazy object FileFields hold) on that settings change, so
the exact code path that runs on Vercel is what's exercised here.
"""
from __future__ import annotations

from accounts.models import Organization
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from batches import tasks
from batches.dbstorage import DatabaseStorage
from batches.models import Batch, StoredFile

_DB_STORAGES = {
    "default": {"BACKEND": "batches.dbstorage.DatabaseStorage"},
    # override_settings replaces the whole STORAGES dict, so carry a
    # staticfiles entry too or anything touching static storage breaks.
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

_CSV_CONTENT = b"id;name;brand\n1;Bela majica;Acme\n"


def _make_batch(org, **kwargs):
    kwargs.setdefault("provider", Batch.Provider.FAKE)
    return Batch.objects.create(organization=org, name="Test batch", **kwargs)


@override_settings(STORAGES=_DB_STORAGES)
class DatabaseStorageFieldTests(TestCase):
    """Round-trips through the real Batch.source_file FileField."""

    def setUp(self):
        self.org = Organization.objects.create(name="Acme", slug="acme")

    def test_save_creates_row_and_reads_back(self):
        batch = _make_batch(self.org)
        batch.source_file.save("catalog.csv", ContentFile(_CSV_CONTENT), save=True)

        stored = StoredFile.objects.get()
        # The stored name is exactly what the FileField persists: the
        # batch_upload_path shape, org-scoped.
        self.assertEqual(stored.name, "orgs/acme/batches/catalog.csv")
        self.assertEqual(stored.size, len(_CSV_CONTENT))

        with batch.source_file.open("rb") as handle:
            self.assertEqual(handle.read(), _CSV_CONTENT)

    def test_name_collision_gets_alternative_name(self):
        first = _make_batch(self.org)
        second = _make_batch(self.org)
        first.source_file.save("catalog.csv", ContentFile(b"one"), save=True)
        second.source_file.save("catalog.csv", ContentFile(b"two"), save=True)

        # exists() answering truthfully is what lets Django's standard
        # get_alternative_name suffixing kick in for the second file.
        names = set(StoredFile.objects.values_list("name", flat=True))
        self.assertEqual(len(names), 2)
        self.assertIn("orgs/acme/batches/catalog.csv", names)
        with first.source_file.open("rb") as handle:
            self.assertEqual(handle.read(), b"one")
        with second.source_file.open("rb") as handle:
            self.assertEqual(handle.read(), b"two")

    def test_run_generation_reads_source_through_storage(self):
        # End to end with NO filesystem media: proves tasks._load_records
        # goes through storage.open (never FieldFile.path, which
        # DatabaseStorage cannot provide).
        batch = _make_batch(self.org)
        batch.source_file.save("catalog.csv", ContentFile(_CSV_CONTENT), save=True)

        tasks.run_generation(batch.pk)

        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.COMPLETED)
        self.assertEqual(batch.items.count(), 1)


class DatabaseStorageBackendTests(TestCase):
    """Backend-level contract, no FileField involved."""

    def setUp(self):
        self.storage = DatabaseStorage()

    def test_exists_delete_size(self):
        StoredFile.objects.create(name="a.txt", content=b"abc", size=3)
        self.assertTrue(self.storage.exists("a.txt"))
        self.assertEqual(self.storage.size("a.txt"), 3)
        self.storage.delete("a.txt")
        self.assertFalse(self.storage.exists("a.txt"))

    def test_delete_missing_is_silent(self):
        self.storage.delete("missing.txt")  # Storage API contract: no error

    def test_open_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.storage.open("missing.txt")

    def test_size_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.storage.size("missing.txt")

    def test_open_write_mode_refused(self):
        StoredFile.objects.create(name="a.txt", content=b"abc", size=3)
        with self.assertRaises(ValueError):
            self.storage.open("a.txt", "wb")

    def test_url_not_supported(self):
        # Uploads are never served by URL -- downloads go through org-scoped
        # views only (same posture as ArtifactDownloadView).
        with self.assertRaises(NotImplementedError):
            self.storage.url("a.txt")
