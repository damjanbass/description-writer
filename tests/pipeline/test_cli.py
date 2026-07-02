"""Tests for the Stage 5 CLI entrypoint (pipeline.cli): `generate`, `review
list/approve/reject`, and `publish`. No network: every case uses --fake
and/or --fake-connector, so the whole pipeline runs offline.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from pipeline import cli, fsio
from pipeline.cli import main
from pipeline.review import ReviewStatus, review_queue_from_json


def _write_catalog(path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "brand", "storage"])
        writer.writerow(["1", "Samsung", "128GB"])
        writer.writerow(["2", "Lenovo", "256GB"])


def _generate(tmp_path, **extra_flags: str):
    catalog = tmp_path / "catalog.csv"
    _write_catalog(catalog)
    out_dir = tmp_path / "out"
    argv = ["generate", str(catalog), "-o", str(out_dir), "--fake"]
    for flag, value in extra_flags.items():
        argv.extend([flag, value])
    exit_code = main(argv)
    return exit_code, out_dir


def _queue(out_dir):
    return review_queue_from_json((out_dir / "review_queue.json").read_text(encoding="utf-8"))


class TestGenerate:
    def test_fake_run_produces_outputs_and_exits_zero(self, tmp_path):
        exit_code, out_dir = _generate(tmp_path)

        assert exit_code == 0
        assert (out_dir / "descriptions.csv").exists()
        assert (out_dir / "provenance" / "1.json").exists()
        assert (out_dir / "provenance" / "2.json").exists()

    def test_fake_run_honors_source_script_flag(self, tmp_path):
        exit_code, out_dir = _generate(tmp_path, **{"--source-script": "latinica"})

        assert exit_code == 0
        assert (out_dir / "descriptions.csv").exists()

    def test_missing_catalog_returns_nonzero(self, tmp_path):
        missing = tmp_path / "does-not-exist.csv"
        out_dir = tmp_path / "out"

        exit_code = main(["generate", str(missing), "-o", str(out_dir), "--fake"])

        assert exit_code != 0
        assert not out_dir.exists()

    def test_unsupported_extension_returns_nonzero(self, tmp_path):
        bad_file = tmp_path / "catalog.txt"
        bad_file.write_text("irrelevant", encoding="utf-8")
        out_dir = tmp_path / "out"

        exit_code = main(["generate", str(bad_file), "-o", str(out_dir), "--fake"])

        assert exit_code != 0

    def test_seeds_review_queue_with_every_product_pending(self, tmp_path):
        exit_code, out_dir = _generate(tmp_path)
        assert exit_code == 0

        queue = _queue(out_dir)
        assert {item.product_id for item in queue.items} == {"1", "2"}
        assert all(item.status is ReviewStatus.PENDING for item in queue.items)


class TestReviewList:
    def test_lists_all_items_with_no_filter(self, tmp_path, capsys):
        _, out_dir = _generate(tmp_path)
        capsys.readouterr()

        exit_code = main(["review", "list", "-o", str(out_dir)])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "1\tpending" in out
        assert "2\tpending" in out

    def test_status_filter_with_no_matches_prints_message(self, tmp_path, capsys):
        _, out_dir = _generate(tmp_path)
        capsys.readouterr()

        exit_code = main(["review", "list", "-o", str(out_dir), "--status", "approved"])

        assert exit_code == 0
        assert "No items match." in capsys.readouterr().out

    def test_missing_queue_returns_nonzero(self, tmp_path):
        out_dir = tmp_path / "out"
        exit_code = main(["review", "list", "-o", str(out_dir)])
        assert exit_code != 0


class TestReviewApprove:
    def test_approve_known_product_updates_queue(self, tmp_path):
        _, out_dir = _generate(tmp_path)

        exit_code = main(["review", "approve", "1", "-o", str(out_dir)])

        assert exit_code == 0
        queue = _queue(out_dir)
        assert queue.get("1").status is ReviewStatus.APPROVED
        assert queue.get("2").status is ReviewStatus.PENDING

    def test_approve_unknown_product_returns_nonzero(self, tmp_path):
        _, out_dir = _generate(tmp_path)

        exit_code = main(["review", "approve", "does-not-exist", "-o", str(out_dir)])

        assert exit_code != 0


class TestReviewReject:
    def test_reject_with_reason_updates_queue(self, tmp_path):
        _, out_dir = _generate(tmp_path)

        exit_code = main(
            ["review", "reject", "2", "-o", str(out_dir), "--reason", "needs human rewrite"]
        )

        assert exit_code == 0
        item = _queue(out_dir).get("2")
        assert item.status is ReviewStatus.REJECTED
        assert item.reason == "needs human rewrite"


class TestPublish:
    def test_publishes_only_approved_items_with_fake_connector(self, tmp_path):
        _, out_dir = _generate(tmp_path)
        main(["review", "approve", "1", "-o", str(out_dir)])

        exit_code = main(
            ["publish", "-o", str(out_dir), "--connector", "woocommerce", "--fake-connector"]
        )

        assert exit_code == 0
        queue = _queue(out_dir)
        assert queue.get("1").status is ReviewStatus.PUBLISHED
        assert queue.get("2").status is ReviewStatus.PENDING

    def test_publish_with_nothing_approved_publishes_zero(self, tmp_path, capsys):
        _, out_dir = _generate(tmp_path)
        capsys.readouterr()

        exit_code = main(
            ["publish", "-o", str(out_dir), "--connector", "woocommerce", "--fake-connector"]
        )

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "Published 0 product(s); 0 failed; 2 not approved (skipped)." in out

    def test_missing_credentials_without_fake_connector_returns_nonzero(self, tmp_path):
        _, out_dir = _generate(tmp_path)

        exit_code = main(["publish", "-o", str(out_dir), "--connector", "woocommerce"])

        assert exit_code != 0

    def test_woocommerce_without_consumer_secret_returns_nonzero(self, tmp_path):
        _, out_dir = _generate(tmp_path)

        exit_code = main(
            [
                "publish",
                "-o",
                str(out_dir),
                "--connector",
                "woocommerce",
                "--base-url",
                "https://shop.example.com",
                "--consumer-key",
                "ck_abc",
            ]
        )

        assert exit_code != 0

    def test_unimplemented_connector_fails_loudly_but_does_not_crash(self, tmp_path, capsys):
        _, out_dir = _generate(tmp_path)
        main(["review", "approve", "1", "-o", str(out_dir)])
        capsys.readouterr()

        exit_code = main(
            [
                "publish",
                "-o",
                str(out_dir),
                "--connector",
                "selltico",
                "--base-url",
                "https://shop.example.com",
                "--consumer-key",
                "key123",
            ]
        )

        # The run completes (exit 0) but reports the failure loudly and leaves
        # the item APPROVED (retryable), exactly the "one bad product must not
        # abort the run" contract pipeline.runner.run_batch already uses.
        assert exit_code == 0
        err = capsys.readouterr().err
        assert "no public Selltico API documentation found" in err
        assert _queue(out_dir).get("1").status is ReviewStatus.APPROVED


class TestPublishCredentials:
    """--consumer-key/--consumer-secret: env var fallback, flag precedence,
    and the argv-visibility warning. Every case stubs `_CONNECTOR_FACTORIES`
    for "woocommerce" so the real `WooCommerceConnector`/network path is
    never exercised - only what `_build_connector` resolves and hands it.
    """

    def _stub_woocommerce_factory(self, monkeypatch):
        captured: dict[str, str | None] = {}

        def _factory(args):
            captured["key"] = args.consumer_key
            captured["secret"] = args.consumer_secret
            return cli._FakeConnector()

        monkeypatch.setitem(cli._CONNECTOR_FACTORIES, "woocommerce", _factory)
        return captured

    def test_env_vars_used_when_flags_omitted(self, tmp_path, monkeypatch):
        _, out_dir = _generate(tmp_path)
        monkeypatch.setenv("KORPUS_CONSUMER_KEY", "env-key")
        monkeypatch.setenv("KORPUS_CONSUMER_SECRET", "env-secret")
        captured = self._stub_woocommerce_factory(monkeypatch)

        exit_code = main(
            [
                "publish",
                "-o",
                str(out_dir),
                "--connector",
                "woocommerce",
                "--base-url",
                "https://shop.example.com",
            ]
        )

        assert exit_code == 0
        assert captured["key"] == "env-key"
        assert captured["secret"] == "env-secret"

    def test_flags_win_over_env_and_warn_without_leaking_values(
        self, tmp_path, monkeypatch, capsys
    ):
        _, out_dir = _generate(tmp_path)
        monkeypatch.setenv("KORPUS_CONSUMER_KEY", "env-key")
        monkeypatch.setenv("KORPUS_CONSUMER_SECRET", "env-secret")
        captured = self._stub_woocommerce_factory(monkeypatch)
        capsys.readouterr()

        exit_code = main(
            [
                "publish",
                "-o",
                str(out_dir),
                "--connector",
                "woocommerce",
                "--base-url",
                "https://shop.example.com",
                "--consumer-key",
                "flag-key",
                "--consumer-secret",
                "flag-secret",
            ]
        )

        assert exit_code == 0
        assert captured["key"] == "flag-key"
        assert captured["secret"] == "flag-secret"
        err = capsys.readouterr().err
        assert "--consumer-key" in err
        assert "--consumer-secret" in err
        assert "flag-key" not in err
        assert "flag-secret" not in err

    def test_neither_flag_nor_env_var_returns_nonzero(self, tmp_path, monkeypatch):
        _, out_dir = _generate(tmp_path)
        monkeypatch.delenv("KORPUS_CONSUMER_KEY", raising=False)
        monkeypatch.delenv("KORPUS_CONSUMER_SECRET", raising=False)

        exit_code = main(
            [
                "publish",
                "-o",
                str(out_dir),
                "--connector",
                "woocommerce",
                "--base-url",
                "https://shop.example.com",
            ]
        )

        assert exit_code != 0


class TestPublishSavePerItem:
    def test_saves_on_disk_after_each_success_not_only_at_the_end(self, tmp_path, monkeypatch):
        _, out_dir = _generate(tmp_path)
        main(["review", "approve", "1", "-o", str(out_dir)])
        main(["review", "approve", "2", "-o", str(out_dir)])
        queue_path = out_dir / "review_queue.json"

        class _PartialFailConnector:
            def fetch_products(self):
                return []

            def push_description(self, product_id, dual, *, publish_script=None):
                if product_id == "2":
                    # By the time item "2" is attempted, item "1"'s publish
                    # must already be durable on disk - proving the queue is
                    # saved per-item, not batched into one save at the end.
                    on_disk = review_queue_from_json(
                        queue_path.read_text(encoding="utf-8")
                    )
                    assert on_disk.get("1").status is ReviewStatus.PUBLISHED
                    assert on_disk.get("2").status is ReviewStatus.APPROVED
                    raise RuntimeError("boom")

        monkeypatch.setattr(cli, "_FakeConnector", lambda: _PartialFailConnector())

        exit_code = main(
            ["publish", "-o", str(out_dir), "--connector", "woocommerce", "--fake-connector"]
        )

        assert exit_code == 0
        final_queue = _queue(out_dir)
        assert final_queue.get("1").status is ReviewStatus.PUBLISHED
        assert final_queue.get("2").status is ReviewStatus.APPROVED


class TestQueueLocking:
    """`review approve/reject` and `publish` wrap load->mutate->save in
    `fsio.file_lock` so two concurrent CLI invocations cannot clobber each
    other's write. These tests simulate a lock already held by another
    process (a pre-existing `.lock` sentinel) and confirm the command times
    out rather than proceeding, leaving the on-disk queue untouched.
    """

    @staticmethod
    def _tiny_timeout(original_lock):
        def _wrapped(path, *, timeout=10.0, poll_interval=0.1):
            return original_lock(path, timeout=0.2, poll_interval=0.05)

        return _wrapped

    @pytest.mark.parametrize(
        "argv_suffix",
        [
            ["review", "approve", "1"],
            ["review", "reject", "1"],
            ["publish", "--connector", "woocommerce", "--fake-connector"],
        ],
        ids=["approve", "reject", "publish"],
    )
    def test_held_lock_times_out_instead_of_mutating_queue(
        self, tmp_path, monkeypatch, capsys, argv_suffix
    ):
        _, out_dir = _generate(tmp_path)
        queue_path = out_dir / "review_queue.json"
        lock_path = Path(str(queue_path) + ".lock")
        lock_path.write_text("", encoding="utf-8")
        capsys.readouterr()

        monkeypatch.setattr(fsio, "file_lock", self._tiny_timeout(fsio.file_lock))

        try:
            exit_code = main([*argv_suffix, "-o", str(out_dir)])
        finally:
            lock_path.unlink(missing_ok=True)

        assert exit_code != 0
        err = capsys.readouterr().err
        assert "Could not acquire lock" in err
        # Nothing was approved/rejected/published before the lock timed out.
        queue = _queue(out_dir)
        assert queue.get("1").status is ReviewStatus.PENDING
        assert queue.get("2").status is ReviewStatus.PENDING
