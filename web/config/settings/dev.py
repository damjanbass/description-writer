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

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
