# syntax=docker/dockerfile:1
#
# Build context is the REPO ROOT, not deploy/:
#   docker build -f deploy/Dockerfile .
#
# The image bakes together the pure-Python engine packages that live at the
# repo root (core/, lang/, pipeline/, connectors/) and the Django project in
# web/, preserving their relative layout under /app so web/manage.py's and
# web/config/wsgi.py's sys.path wiring (repo_root, web_dir) resolves them as
# top-level packages exactly like it does outside Docker.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# --- Python dependencies -----------------------------------------------
# Copied and installed before the rest of the source so this layer is only
# rebuilt when requirements.txt actually changes.
COPY web/requirements.txt web/requirements.txt
RUN pip install --no-cache-dir -r web/requirements.txt

# --- Application source ---------------------------------------------------
# Engine packages (stdlib-only, no extra deps of their own) + pyproject.toml
# (declares them as a package for tooling; not pip-installed here since
# manage.py/wsgi.py put repo_root on sys.path directly) + the Django project.
COPY core/ core/
COPY lang/ lang/
COPY pipeline/ pipeline/
COPY connectors/ connectors/
COPY pyproject.toml pyproject.toml
COPY web/ web/
COPY deploy/entrypoint.sh deploy/entrypoint.sh

# --- Non-root user ---------------------------------------------------------
RUN useradd --uid 1000 --user-group --create-home --shell /usr/sbin/nologin korpus \
    && mkdir -p /data/media \
    && chown -R korpus:korpus /app /data/media \
    && chmod +x deploy/entrypoint.sh

# --- Static files -----------------------------------------------------
# `collectstatic` only reads STATICFILES_DIRS/STATIC_ROOT and writes files to
# disk under /app/web/staticfiles — it does not open a database connection
# and does not touch KORPUS_FERNET_KEY (that key is resolved lazily, per
# request, by connections/crypto.py:get_fernet(), never at import time).
#
# config.settings.prod nonetheless fails loud (by design) if its required
# env vars are missing, so we supply throwaway, obviously-fake values for
# exactly this RUN step. These build-time values are NEVER used at
# container runtime: docker-compose.yml supplies the real ones via
# --env-file/.env when the container actually starts. In particular the
# Fernet key below is a validly-formatted (32 urlsafe-base64-encoded bytes)
# but publicly-known dummy — real deployments MUST set their own
# KORPUS_FERNET_KEY at runtime; using this build-time value in production
# would make every encrypted credential recoverable by anyone with this
# Dockerfile.
RUN DJANGO_SETTINGS_MODULE=config.settings.prod \
    KORPUS_SECRET_KEY="build-time-only-dummy-secret-key-never-used-at-runtime-0000" \
    KORPUS_ALLOWED_HOSTS="build.invalid" \
    KORPUS_FERNET_KEY="oytZ-hw4rdRmDWxO9zcE7YZDkm3bsLMV-yWyJgy9uNk=" \
    POSTGRES_DB="build" \
    POSTGRES_USER="build" \
    POSTGRES_PASSWORD="build" \
    POSTGRES_HOST="build.invalid" \
    POSTGRES_PORT="5432" \
    python web/manage.py collectstatic --noinput

USER korpus

ENTRYPOINT ["deploy/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--chdir", "web", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
