"""Tests for the filesystem helpers (pipeline.fsio)."""

from __future__ import annotations

import pytest

from pipeline.fsio import atomic_write_text, file_lock, neutralize_csv_cell


class TestAtomicWriteText:
    def test_writes_content(self, tmp_path):
        target = tmp_path / "out.txt"
        atomic_write_text(target, "hello ćirilica")

        assert target.read_text(encoding="utf-8") == "hello ćirilica"

    def test_leaves_no_temp_or_lock_residue(self, tmp_path):
        target = tmp_path / "out.txt"
        atomic_write_text(target, "data")

        children = list(tmp_path.iterdir())
        assert children == [target]

    def test_overwrites_existing_file(self, tmp_path):
        target = tmp_path / "out.txt"
        target.write_text("old", encoding="utf-8")

        atomic_write_text(target, "new")

        assert target.read_text(encoding="utf-8") == "new"
        assert list(tmp_path.iterdir()) == [target]


class TestFileLock:
    def test_acquires_free_lock_and_cleans_up(self, tmp_path):
        target = tmp_path / "resource"
        lock_path = tmp_path / "resource.lock"

        with file_lock(target):
            assert lock_path.exists()

        assert not lock_path.exists()

    def test_held_lock_makes_second_acquisition_time_out(self, tmp_path):
        target = tmp_path / "resource"

        with file_lock(target):
            with pytest.raises(TimeoutError) as exc_info:
                with file_lock(target, timeout=0.05, poll_interval=0.01):
                    pass

        assert "resource.lock" in str(exc_info.value)


class TestNeutralizeCsvCell:
    @pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
    def test_dangerous_prefix_is_escaped(self, prefix):
        value = prefix + "HYPERLINK(1)"
        assert neutralize_csv_cell(value) == "'" + value

    @pytest.mark.parametrize("value", ["plain text", "12345", "", "Samsung 128GB"])
    def test_safe_values_are_unchanged(self, value):
        assert neutralize_csv_cell(value) == value
