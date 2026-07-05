"""
Production settings.

Deployed behind Caddy, which terminates TLS and reverse-proxies to
gunicorn — see SECURE_SSL_REDIRECT note below. Task 4D/5C will finalize
deploy-specific details (allowed hosts wiring, secrets management); the
section comments below mark what still needs attention.
"""
import os

from .base import *  # noqa: F401,F403

DEBUG = False

# ---------------------------------------------------------------------------
# Secret key — REQUIRED in prod, no insecure fallback and no weak keys.
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("KORPUS_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "KORPUS_SECRET_KEY environment variable is required in production."
    )
# Fail loud on an obviously weak key (Django's own W009 threshold): at least
# 50 characters and at least 5 distinct characters.
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5:
    raise RuntimeError(
        "KORPUS_SECRET_KEY is too weak: use at least 50 characters with good "
        'entropy. Generate one with: python -c '
        '"import secrets; print(secrets.token_urlsafe(64))"'
    )

# ---------------------------------------------------------------------------
# Hosts / CSRF
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("KORPUS_ALLOWED_HOSTS", "").split(",") if h.strip()
]
if not ALLOWED_HOSTS:
    raise RuntimeError(
        "KORPUS_ALLOWED_HOSTS environment variable is required in production "
        "(comma-separated list of hostnames, e.g. 'korpus.rs,www.korpus.rs')."
    )

CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("KORPUS_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

# ---------------------------------------------------------------------------
# Database — Postgres
# ---------------------------------------------------------------------------
# Two mutually exclusive configuration shapes, checked in this order:
#
# 1. DATABASE_URL — a single connection URL, the shape managed-Postgres
#    providers hand out (Neon via the Vercel Marketplace injects exactly
#    this). Parsed with stdlib urllib.parse — deliberately no dj-database-url
#    dependency for one URL split. Neon's pooled URL goes through pgbouncer
#    in transaction mode, so a connection must never be reused across
#    requests (CONN_MAX_AGE=0) and server-side cursors are unsafe (a cursor
#    can outlive "its" backend connection) — both pinned here. TLS is
#    required by default; a provider that needs otherwise can say so in the
#    URL's own ?sslmode= query parameter.
#
# 2. Discrete POSTGRES_* variables — the compose/VPS deployment shape,
#    unchanged. Fails loud on a missing password rather than silently
#    connecting with "" — consistent with how SECRET_KEY / ALLOWED_HOSTS are
#    enforced above.
_database_url = os.environ.get("DATABASE_URL", "")
if _database_url:
    from urllib.parse import parse_qsl, unquote, urlsplit

    _parsed = urlsplit(_database_url)
    if _parsed.scheme not in ("postgres", "postgresql"):
        raise RuntimeError(
            "DATABASE_URL must be a postgres:// or postgresql:// URL "
            f"(got scheme {_parsed.scheme!r})."
        )
    _query = dict(parse_qsl(_parsed.query))
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(_parsed.path.lstrip("/")),
            "USER": unquote(_parsed.username or ""),
            "PASSWORD": unquote(_parsed.password or ""),
            "HOST": _parsed.hostname or "",
            "PORT": str(_parsed.port) if _parsed.port else "",
            "CONN_MAX_AGE": 0,
            "DISABLE_SERVER_SIDE_CURSORS": True,
            "OPTIONS": {"sslmode": _query.get("sslmode", "require")},
        }
    }
else:
    _postgres_password = os.environ.get("POSTGRES_PASSWORD")
    if not _postgres_password:
        raise RuntimeError(
            "POSTGRES_PASSWORD environment variable is required in production "
            "(or provide a single DATABASE_URL connection URL instead)."
        )

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "korpus"),
            "USER": os.environ.get("POSTGRES_USER", "korpus"),
            "PASSWORD": _postgres_password,
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }

# ---------------------------------------------------------------------------
# Security hardening
# ---------------------------------------------------------------------------
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
# Caddy terminates TLS in front of gunicorn; redirecting to https here too
# would risk a redirect loop on the internal (plain HTTP) hop.
SECURE_SSL_REDIRECT = False

# `check --deploy` raises security.W008 because SECURE_SSL_REDIRECT is False.
# That is intentional here: Caddy (the TLS-terminating reverse proxy) owns the
# HTTP->HTTPS redirect at the edge, so Django must NOT also redirect on the
# internal plain-HTTP hop. Silence only this one check so the rest of the
# deploy audit stays a meaningful zero-warning gate.
SILENCED_SYSTEM_CHECKS = ["security.W008"]

# ---------------------------------------------------------------------------
# Static / media
# ---------------------------------------------------------------------------
# Hashed + gzip/brotli-compressed static files, served directly by WhiteNoise
# (middleware already installed in base.py). Filenames are content-hashed, so
# they're safe to cache forever — see WHITENOISE_MAX_AGE below. Keep the
# Django default for "default" (media uploads) unchanged.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
# Hashed filenames never change contents, so browsers/CDNs may cache them
# indefinitely (1 year, the practical maximum).
WHITENOISE_MAX_AGE = 31536000
# MEDIA_ROOT already resolves from KORPUS_MEDIA_ROOT in base.py; in compose
# deploys that env var points at /data/media, a mounted volume — nothing to
# duplicate here.

# ---------------------------------------------------------------------------
# Email — SMTP, configured via env (task 4D/5C to finalize provider/creds)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("KORPUS_EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("KORPUS_EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("KORPUS_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("KORPUS_EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("KORPUS_EMAIL_USE_TLS", "true").lower() == "true"
DEFAULT_FROM_EMAIL = os.environ.get("KORPUS_DEFAULT_FROM_EMAIL", "no-reply@korpus.rs")

# ---------------------------------------------------------------------------
# Logging — structured lines to stdout (captured by the process manager).
# ---------------------------------------------------------------------------
# Deliberately NEVER logs request bodies: uploaded catalogs and connector
# credentials must not leak into logs. Django does not log request bodies by
# default, and we add nothing that would. django.security warnings (host
# header, CSRF, etc.) are surfaced separately so they stand out.
_APP_LOGGERS = ["accounts", "leads", "connections", "batches", "common"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": (
                "%(asctime)s level=%(levelname)s logger=%(name)s "
                "%(message)s"
            ),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "structured",
            "level": "INFO",
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        # Security-relevant events get their own floor so they are never
        # silently dropped below WARNING.
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        **{
            name: {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            }
            for name in _APP_LOGGERS
        },
    },
}
