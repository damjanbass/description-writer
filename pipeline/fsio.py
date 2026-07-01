"""Filesystem helpers for durable, safe output writing.

These utilities back the batch runner (and, later, the CLI and web layers) with
three concerns that plain `open(...).write(...)` does not address:

- `atomic_write_text` guarantees a reader never observes a half-written file:
  content is written to a sibling temp file, flushed and fsynced, then swapped
  into place with `os.replace`, which is atomic on both Windows and POSIX.
- `file_lock` provides a cross-platform advisory lock via an exclusive-create
  sentinel file, so no `fcntl`/`msvcrt` split is needed.
- `neutralize_csv_cell` defuses CSV/formula injection so a crafted catalog cell
  cannot execute as a spreadsheet formula when the output is opened in Excel or
  similar. It is public here so every layer that emits CSV can reuse it.

Stdlib only.
"""

from __future__ import annotations

import contextlib
import errno
import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

# Leading characters that spreadsheet apps (Excel, LibreOffice Calc, Google
# Sheets) may interpret as the start of a formula. Prefixing the cell with a
# single quote forces the app to treat the whole value as text.
_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write `text` to `path` atomically.

    The content is written to a uniquely named temp file in `path.parent`,
    flushed and fsynced to durable storage, then moved into place with
    `os.replace` (atomic on Windows and POSIX). A reader therefore sees either
    the previous file or the fully written new one, never a partial write. On
    any failure the temp file is removed best-effort and the error re-raised.
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
        encoding=encoding,
        newline="",
    )
    tmp_path = Path(tmp.name)
    try:
        with tmp:
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise


@contextlib.contextmanager
def file_lock(
    path: Path, *, timeout: float = 10.0, poll_interval: float = 0.1
) -> Iterator[Path]:
    """Acquire an advisory lock for `path` via a sibling `.lock` sentinel.

    A sentinel file at ``str(path) + ".lock"`` is created with
    ``O_CREAT | O_EXCL``; if it already exists the call retries every
    `poll_interval` seconds until `timeout` elapses, then raises `TimeoutError`.
    The sentinel is always closed and unlinked on exit. This works identically
    on Windows and POSIX (no `fcntl`).
    """
    lock_path = Path(str(path) + ".lock")
    deadline = time.monotonic() + timeout
    fd: int | None = None
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Could not acquire lock {lock_path} within {timeout}s"
                ) from exc
            time.sleep(poll_interval)
    try:
        yield lock_path
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            lock_path.unlink()


def neutralize_csv_cell(value: str) -> str:
    """Prefix a `'` to a cell whose leading char could start a spreadsheet formula.

    Returns the value unchanged unless it begins with one of the CSV-injection
    trigger characters (``= + - @`` or a leading tab/carriage return), in which
    case a single quote is prepended so spreadsheet apps treat it as literal
    text.
    """
    if value.startswith(_CSV_INJECTION_PREFIXES):
        return "'" + value
    return value
