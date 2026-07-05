"""Local development settings."""
from .base import *  # noqa: F401,F403
from .base import WEB_DIR

DEBUG = True

ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": WEB_DIR / "db.sqlite3",
    }
}

# Synchronous task execution in dev: no separate qcluster process needed,
# django_q runs tasks inline in the request/management-command process.
Q_CLUSTER = {**Q_CLUSTER, "sync": True}  # noqa: F405

# Same inline semantics for the dispatch abstraction (batches.dispatch):
# uploads/publishes finish within the request, no worker or queue needed.
KORPUS_TASK_DISPATCH = "sync"

# Local memory cache in dev: the runserver process is single-process, so
# rate limiting still works, and there's no `createcachetable` step to
# forget (prod keeps the shared DatabaseCache; its table is created by the
# Docker entrypoint).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
