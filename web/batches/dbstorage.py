"""A Django Storage backend that keeps file contents in Postgres.

Serverless platforms (Vercel) give each invocation an ephemeral filesystem,
so FileSystemStorage silently loses uploads there. This backend stores the
bytes in the `batches.StoredFile` table instead: uploaded catalogs are small
(the platform caps request bodies at ~4.5 MB), each file is read back only
once per generation chunk, and keeping the bytes in Postgres means no extra
vendor, identical behavior across deployments, and the same backup story as
the rest of the data.

Selected via STORAGES["default"] in config/settings/vercel.py; every other
settings module keeps FileSystemStorage. The model is resolved lazily
through apps.get_model (precedent: common/org.py) so this module stays
importable from settings before the app registry is ready.
"""
from __future__ import annotations

from django.apps import apps
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class DatabaseStorage(Storage):
    """Store file contents as rows in `batches.StoredFile`.

    Only the Storage methods the app actually exercises are implemented:
    FileField.save() -> `_save`/`exists`/`get_alternative_name` (name
    collisions get Django's standard random suffix because `exists` answers
    truthfully), FieldFile.open() -> `_open`, plus `delete`/`size` for
    completeness and tests. `url` is deliberately not supported — uploads
    are never served by URL; every download goes through an org-scoped view
    (the same posture ArtifactDownloadView takes for artifacts).
    """

    @staticmethod
    def _model():
        return apps.get_model("batches", "StoredFile")

    def _open(self, name, mode="rb"):
        if "w" in mode:
            raise ValueError(
                "DatabaseStorage only supports reading; write via save()."
            )
        row = self._model().objects.filter(name=name).first()
        if row is None:
            raise FileNotFoundError(f"No stored file named {name!r}.")
        # BinaryField comes back as memoryview on Postgres, bytes on SQLite;
        # bytes() normalizes both.
        file = ContentFile(bytes(row.content))
        file.name = name
        return file

    def _save(self, name, content):
        # chunks() handles both in-memory and temp-file uploads and rewinds
        # the file itself, so no explicit seek(0) dance is needed.
        data = b"".join(content.chunks())
        self._model().objects.create(name=name, content=data, size=len(data))
        return name

    def exists(self, name):
        return self._model().objects.filter(name=name).exists()

    def delete(self, name):
        self._model().objects.filter(name=name).delete()

    def size(self, name):
        size = (
            self._model()
            .objects.filter(name=name)
            .values_list("size", flat=True)
            .first()
        )
        if size is None:
            raise FileNotFoundError(f"No stored file named {name!r}.")
        return size

    def url(self, name):
        raise NotImplementedError(
            "DatabaseStorage does not serve files by URL; downloads go "
            "through org-scoped views."
        )
