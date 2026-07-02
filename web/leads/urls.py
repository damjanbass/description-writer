from django.urls import path

from .views import lead_create

urlpatterns = [
    # The landing page fetches exactly "/api/lead" (no trailing slash).
    path("lead", lead_create, name="lead-create"),
    # Trailing-slash alias, in case anything (browser normalization,
    # future callers) hits the endpoint with a trailing slash.
    path("lead/", lead_create, name="lead-create-slash"),
]
