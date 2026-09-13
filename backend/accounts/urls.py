from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("options/", views.sign_in_options, name="options"),
    path("session/", views.session, name="session"),
    path("magic-link/", views.request_magic_link, name="magic-link"),
    path("magic-link/verify/", views.verify_magic_link, name="magic-link-verify"),
    path("sign-out/", views.sign_out, name="sign-out"),
    path("sso/<str:provider>/start/", views.start_sso, name="sso-start"),
]
