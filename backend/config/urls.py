from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/connections/", include("connections.urls")),
    path("api/tickets/", include("tickets.urls")),
]
