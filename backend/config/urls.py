from django.contrib import admin
from django.urls import include, path

from . import settings_api

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/connections/", include("connections.urls")),
    path("api/tickets/", include("tickets.urls")),
    path("api/runs/", include("runs.urls")),
    path("api/settings/", settings_api.workspace_settings, name="workspace-settings"),
    path("api/settings/export-defaults/", settings_api.update_export_defaults, name="export-defaults"),
]
