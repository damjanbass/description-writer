"""Tests for the Stage 5 CLI entrypoint (pipeline.cli): `generate`, `review
list/approve/reject`, and `publish`. No network: every case uses --fake
and/or --fake-connector, so the whole pipeline runs offline.
"""

from __future__ import annotations

import csv

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
