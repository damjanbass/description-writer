#!/usr/bin/env python
"""Django's command-line utility for administrative tasks.

This file adds both the repo root (parent of web/) and web/ itself to
sys.path so that the pure-Python engine packages (`core`, `lang`,
`pipeline`, `connectors`) import directly as top-level packages, and the
`config` package (this project's settings/urls/wsgi) resolves normally.
"""
import os
import sys
from pathlib import Path


def main():
    """Run administrative tasks."""
    web_dir = Path(__file__).resolve().parent
    repo_root = web_dir.parent

    for path in (str(repo_root), str(web_dir)):
        if path not in sys.path:
            sys.path.insert(0, path)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
