"""Tests for the machine-called task endpoint POST /api/tasks/run
(batches.views_tasks.run_task) -- the delivery target for
batches.dispatch's "qstash" mode.

The endpoint is deliberately absent (404) unless KORPUS_TASK_TOKEN is set,
authenticates with a constant-time Bearer-token compare, caps the body
size, and only executes tasks from dispatch.py's explicit allowlist. These
tests pin down that auth matrix plus the execute-inline contract.
"""
from __future__ import annotations

import json
from unittest import mock

from django.test import Client, TestCase, override_settings

_URL = "/api/tasks/run"
_TOKEN_SETTINGS = {"KORPUS_TASK_TOKEN": "task-secret"}
_RUN_GENERATION = "batches.tasks.run_generation"


def _post(client, payload, token="task-secret"):
    kwargs = {"content_type": "application/json"}
    if token is not None:
        kwargs["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    data = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
    return client.post(_URL, data=data, **kwargs)


class RunTaskEndpointDisabledTests(TestCase):
    def test_404_when_token_unset(self):
        # dev settings leave KORPUS_TASK_TOKEN empty: deployments that never
        # dispatch over HTTP must not expose the endpoint at all --
        # indistinguishable from any other unknown URL.
        response = _post(self.client, {"task": _RUN_GENERATION, "args": [1]})
        self.assertEqual(response.status_code, 404)


@override_settings(**_TOKEN_SETTINGS)
class RunTaskAuthTests(TestCase):
    def test_get_is_rejected(self):
        response = self.client.get(_URL, HTTP_AUTHORIZATION="Bearer task-secret")
        self.assertEqual(response.status_code, 405)

    def test_missing_authorization_header(self):
        response = _post(self.client, {"task": _RUN_GENERATION, "args": [1]}, token=None)
        self.assertEqual(response.status_code, 401)

    def test_wrong_token(self):
        response = _post(self.client, {"task": _RUN_GENERATION, "args": [1]}, token="wrong")
        self.assertEqual(response.status_code, 401)

    def test_oversized_body_is_rejected(self):
        big = json.dumps({"task": _RUN_GENERATION, "pad": "a" * (11 * 1024)})
        response = _post(self.client, big)
        self.assertEqual(response.status_code, 413)


@override_settings(**_TOKEN_SETTINGS)
class RunTaskPayloadTests(TestCase):
    def test_non_json_body(self):
        response = _post(self.client, "not json")
        self.assertEqual(response.status_code, 400)

    def test_missing_task_key(self):
        response = _post(self.client, {"args": [1]})
        self.assertEqual(response.status_code, 400)

    def test_task_not_a_string(self):
        response = _post(self.client, {"task": 5, "args": []})
        self.assertEqual(response.status_code, 400)

    def test_args_not_a_list(self):
        response = _post(self.client, {"task": _RUN_GENERATION, "args": {"pk": 1}})
        self.assertEqual(response.status_code, 400)

    def test_unknown_task_refused(self):
        # The whole point of the allowlist: an attacker with a stolen token
        # still cannot name arbitrary callables.
        response = _post(self.client, {"task": "os.system", "args": ["boom"]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Unknown task."})


@override_settings(**_TOKEN_SETTINGS)
class RunTaskExecutionTests(TestCase):
    def test_valid_payload_executes_task_inline(self):
        # enforce_csrf_checks proves the endpoint is csrf_exempt -- QStash
        # cannot carry a CSRF token. The allowlist resolves batches.tasks
        # attributes at call time, so patching the task function is observed.
        csrf_client = Client(enforce_csrf_checks=True)
        with mock.patch("batches.tasks.run_generation") as task:
            response = _post(csrf_client, {"task": _RUN_GENERATION, "args": [123]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        task.assert_called_once_with(123)

    def test_task_exception_returns_500_without_leaking(self):
        # A 500 is the retry signal for QStash; the body must stay opaque.
        with mock.patch(
            "batches.tasks.run_generation",
            side_effect=RuntimeError("secret-internal-detail"),
        ):
            response = _post(self.client, {"task": _RUN_GENERATION, "args": [1]})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"ok": False})
        self.assertNotIn(b"secret-internal-detail", response.content)
        self.assertNotIn(b"Traceback", response.content)
