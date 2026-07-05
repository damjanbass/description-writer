"""URL patterns for the batches app.

Mounted at `/app/<slug:org_slug>/batches/` by `config/urls.py` -- every
pattern here is relative to that prefix, so `org_slug` is already captured
by the time these resolve; `common.org.OrgMembershipRequiredMixin` reads it
off `self.kwargs` in `dispatch()`.
"""
from django.urls import path

from . import views

app_name = "batches"

urlpatterns = [
    path("", views.BatchListView.as_view(), name="list"),
    path("nova/", views.BatchUploadView.as_view(), name="upload"),
    path("demo/", views.DemoSeedView.as_view(), name="demo"),
    path("<int:pk>/", views.BatchDetailView.as_view(), name="detail"),
    path("<int:pk>/status.json", views.BatchStatusView.as_view(), name="status"),
    path("<int:pk>/objavi/", views.BatchPublishView.as_view(), name="publish"),
    path(
        "<int:pk>/artefakt/<str:kind>/",
        views.ArtifactDownloadView.as_view(),
        name="artifact",
    ),
    path(
        "<int:pk>/stavka/<int:item_pk>/",
        views.ReviewItemDetailView.as_view(),
        name="item",
    ),
    path(
        "<int:pk>/stavka/<int:item_pk>/odobri/",
        views.ItemApproveView.as_view(),
        name="item-approve",
    ),
    path(
        "<int:pk>/stavka/<int:item_pk>/odbij/",
        views.ItemRejectView.as_view(),
        name="item-reject",
    ),
]
