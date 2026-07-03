"""URL configuration for the Korpus web project."""
from common.views import RateLimitedLoginView
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("app/", include("accounts.urls")),
    path("app/<slug:org_slug>/batches/", include("batches.urls")),
    path("api/", include("leads.urls")),
    # --- Auth (Django's built-in views, minimal Korpus-styled templates) ---
    path(
        "app/login/",
        RateLimitedLoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("app/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "app/password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset_form.html"
        ),
        name="password_reset",
    ),
    path(
        "app/password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "app/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html"
        ),
        name="password_reset_confirm",
    ),
    path(
        "app/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
