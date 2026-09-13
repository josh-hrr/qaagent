from django.urls import path

from . import views

app_name = "tickets"

urlpatterns = [
    path("", views.list_tickets, name="list"),
]
