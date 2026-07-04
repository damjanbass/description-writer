"""Tests for the in-app guide page (/app/vodic/): reachable when authenticated,
gated behind login otherwise. See common/guide.py and templates/guide.html.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class GuideViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="member", password="pw")

    def test_authenticated_get_renders_guide(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("guide"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Kako Korpus radi", content)
        self.assertIn("NA ČEKANJU", content)
        self.assertIn("NEMA IZVORA", content)
        self.assertIn("korpus-primer.csv", content)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("guide"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/app/login/", response["Location"])
