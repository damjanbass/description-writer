"""How enqueued background work leaves the calling process.

One `dispatch(task_name, *args)` entry point, three transports selected by
`settings.KORPUS_TASK_DISPATCH` (see base.py for the full mode docs):

  "sync"     - run the task inline. Dev + tests: the exact semantics
               dev.py's `Q_CLUSTER["sync"] = True` gives django_q, so
               calling code behaves identically under either mechanism.
  "django_q" - `async_task` passthrough; a qcluster worker process consumes
               the queue (the VPS/compose deployment).
  "qstash"   - publish an HTTPS message to Upstash QStash, which delivers
               it back to this deployment's POST /api/tasks/run
               (batches.views_tasks). For serverless platforms with no
               persistent worker: each delivery runs one bounded chunk of
               work, and the task re-dispatches its own continuation.

SECURITY: task names are resolved through the explicit allowlist below,
never by importing a caller-supplied dotted path — the /api/tasks/run
endpoint feeds attacker-reachable strings into `resolve_task`, and the
allowlist is what keeps that from becoming arbitrary code execution. Every
mode validates the name up front so a typo'd dispatch fails at the call
site, not minutes later in a worker.

The task registry lives in a lazy function (not module level) because
tasks.py imports `dispatch` for continuations — importing tasks here at
module level would be a circular import.
"""
from __future__ import annotations

import json
import logging
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)


def _allowed_tasks() -> dict:
    from . import tasks

    return {
        "batches.tasks.run_generation": tasks.run_generation,
        "batches.tasks.publish_batch": tasks.publish_batch,
    }


def resolve_task(task_name: str):
    """Allowlist lookup of a task callable; ValueError for anything else."""
    try:
        return _allowed_tasks()[task_name]
    except KeyError:
        raise ValueError(f"Unknown task {task_name!r}.") from None


def dispatch(task_name: str, *args) -> None:
    """Hand `task_name(*args)` off per `settings.KORPUS_TASK_DISPATCH`.

    Args must be JSON-serializable scalars (ints/strings/None) — the qstash
    transport round-trips them through a JSON body, and django_q pickles
    them; both hold for the pk/str arguments the batches tasks take.
    """
    task = resolve_task(task_name)
    mode = settings.KORPUS_TASK_DISPATCH

    if mode == "sync":
        task(*args)
    elif mode == "django_q":
        from django_q.tasks import async_task

        async_task(task_name, *args)
    elif mode == "qstash":
        _publish_to_qstash(task_name, args)
    else:
        raise ValueError(
            f"KORPUS_TASK_DISPATCH has unsupported value {mode!r} "
            '(expected "sync", "django_q" or "qstash").'
        )


def _publish_to_qstash(task_name: str, args: tuple) -> None:
    """POST one task message to QStash for delivery to /api/tasks/run.

    QStash forwards any `Upstash-Forward-<Name>` header to the destination
    with the prefix stripped, so the `Upstash-Forward-Authorization` below
    arrives at /api/tasks/run as a plain `Authorization: Bearer ...` header
    — which is what batches.views_tasks verifies. Failures raise so the
    caller's request errors loudly; a batch stranded by a lost dispatch is
    re-kicked by the status endpoint's stall backstop anyway.
    """
    missing = [
        name
        for name, value in (
            ("QSTASH_TOKEN", settings.QSTASH_TOKEN),
            ("KORPUS_TASK_CALLBACK_BASE", settings.KORPUS_TASK_CALLBACK_BASE),
            ("KORPUS_TASK_TOKEN", settings.KORPUS_TASK_TOKEN),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "qstash dispatch requires these settings/env vars: "
            + ", ".join(missing)
        )

    destination = f"{settings.KORPUS_TASK_CALLBACK_BASE}/api/tasks/run"
    url = f"{settings.QSTASH_URL}/v2/publish/{destination}"
    body = json.dumps({"task": task_name, "args": list(args)}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.QSTASH_TOKEN}",
            "Content-Type": "application/json",
            "Upstash-Forward-Authorization": (
                f"Bearer {settings.KORPUS_TASK_TOKEN}"
            ),
        },
    )
    # urlopen raises HTTPError for >=400; anything else in the 2xx/3xx range
    # means QStash accepted the message.
    with urllib.request.urlopen(request, timeout=10):
        pass
    logger.info("dispatch: published %s to QStash.", task_name)
