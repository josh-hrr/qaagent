from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

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

# The built SPA, from the same origin as the API — so the session cookie stays
# first-party and no CORS or SameSite relaxation is needed. Every path that is
# not the API or the admin hands back index.html and lets the router decide;
# an unknown /api/ path still 404s as JSON rather than being swallowed here.
# Only when there is something to serve: in development the app is on the Vite
# dev server, and a catch-all with no index.html turns every typo into a
# template error instead of a 404.
if (settings.FRONTEND_DIST / "index.html").exists():
    urlpatterns += [
        re_path(
            r"^(?!api/|admin/|static/).*$",
            TemplateView.as_view(template_name="index.html"),
            name="spa",
        ),
    ]
