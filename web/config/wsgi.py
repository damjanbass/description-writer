"""
WSGI config for the Korpus web project.

Exposes the WSGI callable as a module-level variable named ``application``.
"""
import os
import sys
from pathlib import Path

from django.core.wsgi import get_wsgi_application

# Ensure the repo root (parent of web/) is importable so the engine
# packages (core, lang, pipeline, connectors) resolve under WSGI servers
# (gunicorn) too, not just via manage.py.
_web_dir = Path(__file__).resolve().parent.parent
_repo_root = _web_dir.parent
for _path in (str(_repo_root), str(_web_dir)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_wsgi_application()
