"""Machine-facing URL patterns for the batches app.

Mounted at `/api/tasks/` by `config/urls.py` -- deliberately OUTSIDE the
org-scoped `/app/<org_slug>/batches/` prefix in `urls.py`, because the
caller (QStash) has no session or org; auth is the shared-secret header
checked in `views_tasks.run_task`.
"""
from django.urls import path

from . import views_tasks

app_name = "batches_api"

urlpatterns = [
    path("run", views_tasks.run_task, name="task-run"),
]
