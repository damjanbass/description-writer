"""
Vercel serverless settings.

Inherits everything from prod.py, whose import-time requirements are all
satisfied by Vercel project env vars: KORPUS_SECRET_KEY,
KORPUS_ALLOWED_HOSTS and KORPUS_CSRF_TRUSTED_ORIGINS are set explicitly,
and the Neon Marketplace integration injects DATABASE_URL (which prod.py
now accepts in place of discrete POSTGRES_* variables). Only what genuinely
differs on a serverless platform is overridden here:

- No persistent disk -> uploaded catalog files live in Postgres via
  batches.dbstorage.DatabaseStorage instead of FileSystemStorage.
- No persistent worker process -> background work is dispatched to Upstash
  QStash, which calls back into POST /api/tasks/run; each invocation
  processes a bounded chunk and re-dispatches its own continuation
  (see batches/dispatch.py and batches/tasks.py).

Vercel's edge terminates TLS in front of the function - the same shape as
Caddy in the VPS deployment - so prod.py's SECURE_SSL_REDIRECT=False and
SECURE_PROXY_SSL_HEADER carry over correctly; nothing to override there.
Static files keep prod's WhiteNoise manifest storage: collectstatic runs at
build time and its output ships read-only inside the function bundle.
"""
import os

from .prod import *  # noqa: F401,F403
from .prod import STORAGES

# Uploads go to Postgres (module docstring). "staticfiles" stays WhiteNoise.
STORAGES = {
    **STORAGES,
    "default": {"BACKEND": "batches.dbstorage.DatabaseStorage"},
}

# Chunked background work via QStash. Still env-overridable - e.g. "sync"
# for a one-off management command run against the production database.
KORPUS_TASK_DISPATCH = os.environ.get("KORPUS_TASK_DISPATCH", "qstash")

# Fluid compute caps a Hobby-plan invocation at 300s. 240s leaves headroom
# for the slowest single product (LLM retries) plus the final progress
# writes before the platform would kill the invocation mid-write.
_task_budget = os.environ.get("KORPUS_TASK_TIME_BUDGET_SECONDS", "240")
KORPUS_TASK_TIME_BUDGET_SECONDS = int(_task_budget) if _task_budget else None
