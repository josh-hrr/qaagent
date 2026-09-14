from django.urls import path

from . import views

app_name = "runs"

urlpatterns = [
    path("", views.list_runs, name="list"),
    path("start/", views.start_run, name="start"),
    path("<int:run_id>/", views.run_detail, name="detail"),
    path("<int:run_id>/cancel/", views.cancel_run, name="cancel"),
]
