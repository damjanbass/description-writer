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
# Secret key — REQUIRED in prod, no insecure fallback.
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("KORPUS_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "KORPUS_SECRET_KEY environment variable is required in production."
    )

# ---------------------------------------------------------------------------
# Hosts / CSRF
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("KORPUS_ALLOWED_HOSTS", "").split(",") if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("KORPUS_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

# ---------------------------------------------------------------------------
# Database — Postgres
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "korpus"),
        "USER": os.environ.get("POSTGRES_USER", "korpus"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
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
