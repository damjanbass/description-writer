"""
Base Django settings for the Korpus web project, shared by dev and prod.

This project wraps the pure-Python, stdlib-only engine living at the repo
root (core/, lang/, pipeline/, connectors/) as a library. See
manage.py / wsgi.py for the sys.path wiring that makes those packages
importable from here.
"""
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# web/config/settings/base.py -> parents[0]=settings, [1]=config, [2]=web
WEB_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = WEB_DIR.parent

# Idempotent: make sure the engine packages (core, lang, pipeline,
# connectors) and this project's own `config` package are importable
# regardless of how settings got loaded (management command, WSGI, shell).
for _path in (str(REPO_ROOT), str(WEB_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import os  # noqa: E402

# ---------------------------------------------------------------------------
# Core / security
# ---------------------------------------------------------------------------
# Dev-only insecure default so `manage.py check` etc. work out of the box
# locally. Every real deployment MUST set KORPUS_SECRET_KEY explicitly
# (prod.py enforces this).
SECRET_KEY = os.environ.get(
    "KORPUS_SECRET_KEY", "dev-insecure-secret-key-do-not-use-in-production"
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_q",
    "accounts",
    "leads",
    "connections",
    "batches",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [WEB_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LOGIN_URL = "/app/login/"
LOGIN_REDIRECT_URL = "/app/"
LOGOUT_REDIRECT_URL = "/app/login/"

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "sr-latn"
TIME_ZONE = "Europe/Belgrade"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static / media
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [WEB_DIR / "static"]
STATIC_ROOT = WEB_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("KORPUS_MEDIA_ROOT", str(WEB_DIR / "media")))

# ---------------------------------------------------------------------------
# Django-Q2 (background tasks)
# ---------------------------------------------------------------------------
Q_CLUSTER = {
    "name": "korpus",
    "orm": "default",
    "retry": 720,
    "timeout": 600,
    "max_attempts": 2,
}

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
# django-ratelimit needs a shared cache backend (not per-process LocMem) so
# limits are enforced consistently across worker processes. Uses the
# database as the shared store; run `manage.py createcachetable` once per
# environment (also done automatically in CI/deploy scripts).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "korpus_cache",
    }
}

# django-ratelimit stores counters in a cache; point it explicitly at the
# shared "default" backend above rather than relying on its implicit default.
RATELIMIT_USE_CACHE = "default"

# ---------------------------------------------------------------------------
# Session / cookie hardening (env-independent; prod.py adds the *_SECURE flags)
# ---------------------------------------------------------------------------
# JS can never read the session cookie (default True, stated explicitly).
SESSION_COOKIE_HTTPONLY = True
# Don't send cookies on cross-site requests; still allows top-level nav.
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
# Sessions live 12h then require re-login; caps the window of a stolen cookie.
SESSION_COOKIE_AGE = 12 * 60 * 60
# Keep the 12h lifetime across browser restarts rather than expiring on close.
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# ---------------------------------------------------------------------------
# Upload limits
# ---------------------------------------------------------------------------
# Reject request bodies over 50 MB before parsing — aligned with the batch
# upload cap so oversized uploads fail fast instead of exhausting memory.
DATA_UPLOAD_MAX_MEMORY_SIZE = 52_428_800  # 50 MB
# Files larger than 5 MB stream to a temp file on disk instead of buffering
# the whole thing in memory.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5 MB
