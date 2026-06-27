"""Tests for the Stage 5 CLI entrypoint (pipeline.cli). No network: every
case uses --fake, so the whole pipeline runs offline.
"""

from __future__ import annotations

import csv

from pipeline.cli import main


def _write_catalog(path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "brand", "storage"])
        writer.writerow(["1", "Samsung", "128GB"])
        writer.writerow(["2", "Lenovo", "256GB"])


class TestMain:
    def test_fake_run_produces_outputs_and_exits_zero(self, tmp_path):
        catalog = tmp_path / "catalog.csv"
        _write_catalog(catalog)
        out_dir = tmp_path / "out"

        exit_code = main([str(catalog), "-o", str(out_dir), "--fake"])

        assert exit_code == 0
        assert (out_dir / "descriptions.csv").exists()
        assert (out_dir / "provenance" / "1.json").exists()
        assert (out_dir / "provenance" / "2.json").exists()

    def test_fake_run_honors_source_script_flag(self, tmp_path):
        catalog = tmp_path / "catalog.csv"
        _write_catalog(catalog)
        out_dir = tmp_path / "out"

        exit_code = main(
            [str(catalog), "-o", str(out_dir), "--fake", "--source-script", "latinica"]
        )

        assert exit_code == 0
        assert (out_dir / "descriptions.csv").exists()

    def test_missing_catalog_returns_nonzero(self, tmp_path):
        missing = tmp_path / "does-not-exist.csv"
        out_dir = tmp_path / "out"

        exit_code = main([str(missing), "-o", str(out_dir), "--fake"])

        assert exit_code != 0
        assert not out_dir.exists()

    def test_unsupported_extension_returns_nonzero(self, tmp_path):
        bad_file = tmp_path / "catalog.txt"
        bad_file.write_text("irrelevant", encoding="utf-8")
        out_dir = tmp_path / "out"

        exit_code = main([str(bad_file), "-o", str(out_dir), "--fake"])

        assert exit_code != 0
