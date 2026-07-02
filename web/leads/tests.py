import json
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings

from .models import Lead

LEAD_URL = "/api/lead"

LOCMEM_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}


def _post(client, payload, origin="http://testserver", referer=None, **extra):
    headers = {}
    if origin is not None:
        headers["HTTP_ORIGIN"] = origin
    if referer is not None:
        headers["HTTP_REFERER"] = referer
    headers.update(extra)
    return client.post(
        LEAD_URL,
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )


@override_settings(CACHES=LOCMEM_CACHES)
class LeadCreateTests(TestCase):
    def setUp(self):
        # Each test gets a clean rate-limit counter.
        from django.core.cache import cache

        cache.clear()

    def test_valid_post_creates_lead_and_sends_mail(self):
        response = _post(
            self.client,
            {
                "ime": "Pera Peric",
                "email": "pera@example.com",
                "firma": "Acme d.o.o.",
                "poruka": "Zdravo, zanima me ponuda.",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"ok": True})

        self.assertEqual(Lead.objects.count(), 1)
        lead = Lead.objects.get()
        self.assertEqual(lead.name, "Pera Peric")
        self.assertEqual(lead.email, "pera@example.com")
        self.assertEqual(lead.company, "Acme d.o.o.")
        self.assertEqual(lead.message, "Zdravo, zanima me ponuda.")

        self.assertEqual(len(mail.outbox), 1)

    def test_honeypot_tripped_returns_ok_but_does_not_store(self):
        response = _post(
            self.client,
            {
                "ime": "Bot",
                "email": "bot@example.com",
                "firma": "",
                "poruka": "",
                "website": "http://spam.example",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(Lead.objects.count(), 0)

    def test_missing_email_returns_400(self):
        response = _post(
            self.client,
            {"ime": "Pera Peric", "email": "", "firma": "", "poruka": ""},
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("email", body["errors"])
        self.assertEqual(Lead.objects.count(), 0)

    def test_bad_origin_returns_403(self):
        response = _post(
            self.client,
            {
                "ime": "Pera Peric",
                "email": "pera@example.com",
                "firma": "",
                "poruka": "",
            },
            origin="https://evil.example",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Lead.objects.count(), 0)

    def test_no_origin_and_no_referer_returns_403(self):
        response = _post(
            self.client,
            {
                "ime": "Pera Peric",
                "email": "pera@example.com",
                "firma": "",
                "poruka": "",
            },
            origin=None,
            referer=None,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Lead.objects.count(), 0)

    def test_get_returns_405(self):
        response = self.client.get(LEAD_URL)
        self.assertEqual(response.status_code, 405)

    def test_sixth_request_in_an_hour_is_rate_limited(self):
        payload = {
            "ime": "Pera Peric",
            "email": "pera@example.com",
            "firma": "",
            "poruka": "",
        }
        for _ in range(5):
            response = _post(self.client, payload)
            self.assertEqual(response.status_code, 201)

        response = _post(self.client, payload)
        self.assertEqual(response.status_code, 429)

    def test_email_failure_does_not_lose_lead_or_fail_response(self):
        with patch("leads.views.send_mail", side_effect=RuntimeError("smtp down")):
            response = _post(
                self.client,
                {
                    "ime": "Pera Peric",
                    "email": "pera@example.com",
                    "firma": "",
                    "poruka": "",
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Lead.objects.count(), 1)
