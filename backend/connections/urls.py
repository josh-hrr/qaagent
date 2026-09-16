from django.urls import path

from . import views

app_name = "connections"

urlpatterns = [
    path("", views.list_connections, name="list"),
    path("linear/verify/", views.verify_linear, name="linear-verify"),
    path("linear/", views.connect_linear, name="linear-connect"),
    path("linear/teams/", views.update_linear_teams, name="linear-teams"),
    path("linear/reverify/", views.reverify_linear, name="linear-reverify"),
    path("linear/disconnect/", views.disconnect_linear, name="linear-disconnect"),
    path("azure/verify/", views.verify_azure, name="azure-verify"),
    path("azure/", views.connect_azure, name="azure-connect"),
    path("azure/settings/", views.update_azure_settings, name="azure-settings"),
    path("azure/reverify/", views.reverify_azure, name="azure-reverify"),
    path("azure/disconnect/", views.disconnect_azure, name="azure-disconnect"),
]
