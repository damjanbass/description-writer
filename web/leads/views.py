"""Public lead-capture endpoint for the static landing page.

The landing page (landing/korpus.js) is a plain static HTML/JS file served
by Caddy on the same domain — it is NOT rendered by Django, so there is no
Django-issued CSRF token available to include in the POST. That rules out
the normal CSRF-token defense for this one endpoint.

This view is therefore deliberately `@csrf_exempt`, and that decision is
compensated for by a layered set of defenses appropriate for a public,
session-less, same-site JSON endpoint:

  1. Rate limiting by IP (django-ratelimit) — caps abuse volume.
  2. Origin/Referer host checking — rejects cross-site POSTs whose Origin
     or Referer header doesn't match our own host (a lightweight
     same-origin check standing in for the CSRF token).
  3. A honeypot field ("website") — silently swallows simple bots.
  4. Strict payload size/shape/field validation.

This combination is the accepted pattern for public endpoints that don't
use session-authenticated state-changing requests (there is no session /
cookie-based privilege for an attacker to ride here — worst case of a
forged request is a spurious Lead row).
"""
import json
import logging
import os
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit

from .models import Lead

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 10 * 1024  # 10KB
MAX_MESSAGE_LENGTH = 5000

# Where lead notification emails are sent. Read from env with a sane
# default so this works out of the box in dev.
LEAD_NOTIFY_EMAIL = os.environ.get("LEAD_NOTIFY_EMAIL", "damjan9494@gmail.com")


def _host_of(value):
    """Extract a bare host[:port] from a URL-ish header value."""
    if not value:
        return ""
    parsed = urlparse(value)
    return parsed.netloc or parsed.path


def _origin_or_referer_allowed(request):
    """Same-origin check standing in for CSRF token validation.

    If an Origin header is present it must match either a
    CSRF_TRUSTED_ORIGINS entry or the request's own host. If Origin is
    absent, fall back to the same check against Referer. If neither
    header is present, reject.
    """
    trusted_hosts = {
        _host_of(o) for o in getattr(settings, "CSRF_TRUSTED_ORIGINS", [])
    }
    own_host = request.get_host()

    origin = request.META.get("HTTP_ORIGIN")
    if origin:
        origin_host = _host_of(origin)
        return bool(origin_host) and (
            origin_host == own_host or origin_host in trusted_hosts
        )

    referer = request.META.get("HTTP_REFERER")
    if referer:
        referer_host = _host_of(referer)
        return bool(referer_host) and (
            referer_host == own_host or referer_host in trusted_hosts
        )

    return False


@csrf_exempt
@ratelimit(key="ip", rate="5/h", method="POST", block=False)
def lead_create(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method_not_allowed"}, status=405)

    if getattr(request, "limited", False):
        return JsonResponse({"ok": False, "error": "rate_limited"}, status=429)

    if not _origin_or_referer_allowed(request):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    # Check the declared length BEFORE touching request.body -- reading the
    # body materializes up to DATA_UPLOAD_MAX_MEMORY_SIZE (50 MB) in memory,
    # so an oversized request must be rejected from the header alone.
    try:
        content_length = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        content_length = 0
    if content_length > MAX_BODY_BYTES:
        return JsonResponse({"ok": False, "error": "payload_too_large"}, status=413)

    if len(request.body or b"") > MAX_BODY_BYTES:
        return JsonResponse({"ok": False, "error": "payload_too_large"}, status=413)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        # RecursionError: a deeply nested JSON body (e.g. 10 KB of "[")
        # blows the parser's stack -- treat it as invalid input, not a 500.
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    if not isinstance(data, dict):
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    # Honeypot: bots posting directly may include this hidden field even
    # though the client-side JS never sends it. Pretend success without
    # storing anything so bots can't distinguish a trip from a real save.
    if data.get("website"):
        return JsonResponse({"ok": True}, status=200)

    name = (data.get("ime") or "").strip()
    email = (data.get("email") or "").strip()
    company = (data.get("firma") or "").strip()
    message = (data.get("poruka") or "").strip()

    errors = {}
    if not name:
        errors["ime"] = "required"
    if not email:
        errors["email"] = "required"
    else:
        try:
            validate_email(email)
        except ValidationError:
            errors["email"] = "invalid"
    if len(message) > MAX_MESSAGE_LENGTH:
        errors["poruka"] = "too_long"

    if errors:
        return JsonResponse({"ok": False, "errors": errors}, status=400)

    lead = Lead.objects.create(
        name=name,
        email=email,
        company=company,
        message=message,
    )

    # Best-effort notification: the Lead row is already saved above, so a
    # failure here must never lose the lead or fail the response.
    try:
        send_mail(
            subject="Novi lead sa landing stranice",
            message=f"Novi lead je stigao (id={lead.pk}).",
            from_email=None,
            recipient_list=[LEAD_NOTIFY_EMAIL],
            fail_silently=False,
        )
    except Exception:
        logger.warning("lead notification email failed to send", exc_info=True)

    return JsonResponse({"ok": True}, status=201)
