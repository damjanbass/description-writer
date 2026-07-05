"""Tests for batches.dispatch: the allowlist plus the three-transport
dispatch() used to hand background work off to sync/django_q/qstash
execution (see dispatch.py's module docstring for the full transport
rundown).

The allowlist check is the security boundary here -- POST /api/tasks/run
(batches.views_tasks) feeds attacker-reachable strings into resolve_task --
so it is exercised on its own first, then proven to run before any
transport-specific side effect in every mode. The per-mode test classes
below each prove one transport's wire format/side effects in isolation via
mocking; nothing here talks to a real queue or network.
"""
from __future__ import annotations

import json
from unittest import mock

from django.test import TestCase, override_settings

from batches import dispatch

RUN_GENERATION = "batches.tasks.run_generation"
PUBLISH_BATCH = "batches.tasks.publish_batch"

# Baseline settings a "qstash" dispatch needs to build and send its HTTP
# request; individual tests override just the one var they're exercising
# the absence of.
QSTASH_SETTINGS = {
    "KORPUS_TASK_DISPATCH": "qstash",
    "QSTASH_TOKEN": "qstash-tok",
    "QSTASH_URL": "https://qstash.example",
    "KORPUS_TASK_CALLBACK_BASE": "https://app.example",
    "KORPUS_TASK_TOKEN": "task-secret",
}


class ResolveTaskTests(TestCase):
    """resolve_task is the allowlist lookup both dispatch() and the
    /api/tasks/run view depend on for "never import a caller-supplied
    dotted path".
    """

    def test_known_names_resolve_to_the_task_callables(self):
        from batches import tasks

        self.assertIs(dispatch.resolve_task(RUN_GENERATION), tasks.run_generation)
        self.assertIs(dispatch.resolve_task(PUBLISH_BATCH), tasks.publish_batch)

    def test_unknown_name_raises_value_error(self):
        with self.assertRaises(ValueError) as cm:
            dispatch.resolve_task("os.system")
        self.assertIn("os.system", str(cm.exception))

    def test_lookup_is_lazy_and_reflects_a_patched_task_attribute(self):
        # The allowlist dict is built fresh from `batches.tasks` attributes
        # inside resolve_task, not captured once at dispatch.py import time
        # -- this is what lets "sync" mode dispatch observe a patched
        # batches.tasks.run_generation (see DispatchSyncModeTests below).
        with mock.patch("batches.tasks.run_generation") as mock_task:
            self.assertIs(dispatch.resolve_task(RUN_GENERATION), mock_task)


class DispatchValidatesNameFirstTests(TestCase):
    """The allowlist check in dispatch() must run before any transport-
    specific work, in every mode -- an unknown name must never reach
    async_task or QStash.
    """

    def test_unknown_name_raises_even_with_an_unsupported_mode(self):
        # resolve_task() is the first line of dispatch(), before `mode` is
        # even read. If validation instead happened inside the mode
        # dispatch, this exact combination would raise the *other*
        # ValueError ("unsupported value 'not-a-real-mode'") -- so asserting
        # the message names the unknown task, not the mode, pins the order.
        with override_settings(KORPUS_TASK_DISPATCH="not-a-real-mode"):
            with self.assertRaises(ValueError) as cm:
                dispatch.dispatch("os.system")
        self.assertIn("os.system", str(cm.exception))

    @override_settings(KORPUS_TASK_DISPATCH="sync")
    def test_unknown_name_raises_before_calling_anything_in_sync_mode(self):
        with mock.patch("batches.tasks.run_generation") as mock_task:
            with self.assertRaises(ValueError):
                dispatch.dispatch("os.system", 1)
        mock_task.assert_not_called()

    @override_settings(KORPUS_TASK_DISPATCH="django_q")
    def test_unknown_name_raises_before_enqueueing_in_django_q_mode(self):
        with mock.patch("django_q.tasks.async_task") as mock_async:
            with self.assertRaises(ValueError):
                dispatch.dispatch("os.system", 1)
        mock_async.assert_not_called()

    @override_settings(**QSTASH_SETTINGS)
    def test_unknown_name_raises_before_publishing_in_qstash_mode(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            with self.assertRaises(ValueError):
                dispatch.dispatch("os.system", 1)
        mock_urlopen.assert_not_called()


class DispatchSyncModeTests(TestCase):
    @override_settings(KORPUS_TASK_DISPATCH="sync")
    def test_calls_the_task_inline_with_the_given_args(self):
        with mock.patch("batches.tasks.run_generation") as mock_task:
            result = dispatch.dispatch(RUN_GENERATION, 123)
        mock_task.assert_called_once_with(123)
        self.assertIsNone(result)

    @override_settings(KORPUS_TASK_DISPATCH="sync")
    def test_passes_through_multiple_args(self):
        with mock.patch("batches.tasks.publish_batch") as mock_task:
            dispatch.dispatch(PUBLISH_BATCH, 1, 2, "latinica", 3)
        mock_task.assert_called_once_with(1, 2, "latinica", 3)


class DispatchDjangoQModeTests(TestCase):
    @override_settings(KORPUS_TASK_DISPATCH="django_q")
    def test_enqueues_via_async_task_and_does_not_call_the_task_directly(self):
        with mock.patch("django_q.tasks.async_task") as mock_async:
            with mock.patch("batches.tasks.run_generation") as mock_task:
                dispatch.dispatch(RUN_GENERATION, 123, "abc")
        mock_async.assert_called_once_with(RUN_GENERATION, 123, "abc")
        mock_task.assert_not_called()


class DispatchQstashModeTests(TestCase):
    @override_settings(**QSTASH_SETTINGS)
    def test_publishes_the_expected_request_to_qstash(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            dispatch.dispatch(RUN_GENERATION, 123)

        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 10)

        self.assertEqual(
            request.full_url,
            "https://qstash.example/v2/publish/https://app.example/api/tasks/run",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            json.loads(request.data), {"task": RUN_GENERATION, "args": [123]}
        )

        # urllib.request.Request stores header keys via str.capitalize()
        # ("Content-Type" -> "Content-type", "Upstash-Forward-Authorization"
        # -> "Upstash-forward-authorization") but get_header() does NOT
        # normalize the name it's given -- so lookups must use the stored
        # capitalization. HTTP headers are case-insensitive on the wire, so
        # this quirk is test-only.
        self.assertEqual(request.get_header("Authorization"), "Bearer qstash-tok")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(
            request.get_header("Upstash-forward-authorization"), "Bearer task-secret"
        )

    @override_settings(**QSTASH_SETTINGS)
    def test_no_args_sends_an_empty_args_list(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            dispatch.dispatch(PUBLISH_BATCH)
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(json.loads(request.data)["args"], [])

    def test_missing_qstash_token_raises_runtime_error(self):
        settings_without_token = {**QSTASH_SETTINGS, "QSTASH_TOKEN": ""}
        with override_settings(**settings_without_token):
            with mock.patch("urllib.request.urlopen") as mock_urlopen:
                with self.assertRaises(RuntimeError) as cm:
                    dispatch.dispatch(RUN_GENERATION, 1)
        mock_urlopen.assert_not_called()
        self.assertIn("QSTASH_TOKEN", str(cm.exception))

    def test_missing_callback_base_raises_runtime_error(self):
        settings_without_base = {**QSTASH_SETTINGS, "KORPUS_TASK_CALLBACK_BASE": ""}
        with override_settings(**settings_without_base):
            with mock.patch("urllib.request.urlopen") as mock_urlopen:
                with self.assertRaises(RuntimeError) as cm:
                    dispatch.dispatch(RUN_GENERATION, 1)
        mock_urlopen.assert_not_called()
        self.assertIn("KORPUS_TASK_CALLBACK_BASE", str(cm.exception))

    def test_missing_task_token_raises_runtime_error(self):
        settings_without_task_token = {**QSTASH_SETTINGS, "KORPUS_TASK_TOKEN": ""}
        with override_settings(**settings_without_task_token):
            with mock.patch("urllib.request.urlopen") as mock_urlopen:
                with self.assertRaises(RuntimeError) as cm:
                    dispatch.dispatch(RUN_GENERATION, 1)
        mock_urlopen.assert_not_called()
        self.assertIn("KORPUS_TASK_TOKEN", str(cm.exception))

    def test_all_three_missing_names_all_three_in_the_message(self):
        settings_all_missing = {
            **QSTASH_SETTINGS,
            "QSTASH_TOKEN": "",
            "KORPUS_TASK_CALLBACK_BASE": "",
            "KORPUS_TASK_TOKEN": "",
        }
        with override_settings(**settings_all_missing):
            with self.assertRaises(RuntimeError) as cm:
                dispatch.dispatch(RUN_GENERATION, 1)
        message = str(cm.exception)
        self.assertIn("QSTASH_TOKEN", message)
        self.assertIn("KORPUS_TASK_CALLBACK_BASE", message)
        self.assertIn("KORPUS_TASK_TOKEN", message)


class DispatchUnsupportedModeTests(TestCase):
    @override_settings(KORPUS_TASK_DISPATCH="carrier-pigeon")
    def test_unsupported_mode_raises_value_error(self):
        with self.assertRaises(ValueError) as cm:
            dispatch.dispatch(RUN_GENERATION, 1)
        self.assertIn("carrier-pigeon", str(cm.exception))
