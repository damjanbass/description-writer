"""Machine-called task callback endpoint: QStash delivers dispatched
background work here as HTTPS POSTs (see batches/dispatch.py's "qstash"
mode).

This is a machine endpoint with no session, no user and no org slug, so it
follows `leads.views.lead_create`'s posture (csrf_exempt + strict in-body
validation + a body-size cap) rather than the org-scoped mixin stack --
with a shared-secret Authorization header in place of Origin checks,
because the caller is a queue, not a browser. Deliberately NOT rate-limited:
the token gate already restricts callers, legitimate traffic is ~one
request per chunk (minutes apart), and a limiter here could break a
generation chain mid-batch.

The task name from the body is resolved through `dispatch.resolve_task`'s
explicit allowlist -- never imported as a dotted path -- so this endpoint
cannot be steered into arbitrary code even with a stolen token.
"""
from __future__ import annotations

import hmac
import json
import logging

from django.conf import settings
from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .dispatch import resolve_task

logger = logging.getLogger(__name__)

# Task payloads are {"task": <name>, "args": [pk, ...]} -- tiny. Anything
# bigger than this is not a legitimate dispatch.
MAX_BODY_BYTES = 10 * 1024


@csrf_exempt
def run_task(request):
    """Execute one allowlisted background task synchronously.

    The task itself self-budgets (KORPUS_TASK_TIME_BUDGET_SECONDS) safely
    under the platform's invocation limit, so running it inline here is the
    point: this invocation IS the worker for one chunk. A non-2xx response
    makes QStash retry the delivery -- desired for transient crashes, and
    safe because both tasks are idempotent per product/item.
    """
    if not settings.KORPUS_TASK_TOKEN:
        # Deployments that never dispatch over HTTP (VPS/django_q, dev) have
        # no token configured; the endpoint then doesn't exist at all --
        # indistinguishable from any other unknown URL.
        raise Http404
    if request.method != "POST":
        return JsonResponse({"error": "POST only."}, status=405)

    provided = request.headers.get("Authorization", "")
    expected = f"Bearer {settings.KORPUS_TASK_TOKEN}"
    if not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        return JsonResponse({"error": "Unauthorized."}, status=401)

    # Content-Length pre-check before touching request.body, then the real
    # length -- same two-step cap lead_create uses.
    try:
        content_length = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        content_length = MAX_BODY_BYTES + 1
    if content_length > MAX_BODY_BYTES or len(request.body) > MAX_BODY_BYTES:
        return JsonResponse({"error": "Body too large."}, status=413)

    try:
        payload = json.loads(request.body)
        task_name = payload["task"]
        args = payload.get("args", [])
        if not isinstance(task_name, str) or not isinstance(args, list):
            raise ValueError("Malformed payload.")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return JsonResponse({"error": "Malformed payload."}, status=400)

    try:
        task = resolve_task(task_name)
    except ValueError:
        return JsonResponse({"error": "Unknown task."}, status=400)

    try:
        task(*args)
    except Exception:  # noqa: BLE001 - never leak internals to the caller
        # Full traceback to the log only; the 500 tells QStash to retry.
        logger.exception("run_task: %s raised.", task_name)
        return JsonResponse({"ok": False}, status=500)

    return JsonResponse({"ok": True})
