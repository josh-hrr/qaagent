from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import login, logout
from django.middleware.csrf import get_token
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from .permissions import CsrfProtected
from .serializers import (
    MagicLinkRequestSerializer,
    MagicLinkVerifySerializer,
    UserSerializer,
)
from .services import (
    SignInError,
    client_ip,
    consume_magic_link,
    magic_link_rate_limited,
    send_magic_link,
    sso_provider_statuses,
)

log = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([AllowAny])
def sign_in_options(request: Request) -> Response:
    """What the sign-in screen should offer, and a CSRF cookie to go with it.

    The screen renders from this rather than hardcoding providers, so a provider
    without credentials is shown as unavailable instead of failing on click.
    """
    get_token(request)  # sets the CSRF cookie the SPA echoes back on POSTs
    return Response(
        {
            "providers": [
                {"key": p.key, "label": p.label, "configured": p.configured}
                for p in sso_provider_statuses()
            ],
            "magicLinkEnabled": True,
            "allowedEmailDomains": settings.ALLOWED_EMAIL_DOMAINS,
            "magicLinkTtlMinutes": settings.MAGIC_LINK_TTL_MINUTES,
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def session(request: Request) -> Response:
    """The signed-in user, or 401. The SPA calls this on boot to restore state."""
    request.user.last_seen_at = timezone.now()
    request.user.save(update_fields=["last_seen_at"])
    return Response({"user": UserSerializer(request.user).data})


@api_view(["POST"])
@permission_classes([AllowAny, CsrfProtected])
def request_magic_link(request: Request) -> Response:
    serializer = MagicLinkRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    email = serializer.validated_data["email"]
    ip = client_ip(request)

    if magic_link_rate_limited(email, ip):
        return Response(
            {
                "detail": "Too many sign-in links requested. Try again in an hour.",
                "code": "rate_limited",
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    try:
        send_magic_link(
            email,
            ip=ip,
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
    except Exception:  # noqa: BLE001 — the sender's failure is ours, not the caller's
        log.exception("Could not send a magic link to %s", email)
        return Response(
            {
                "detail": "The sign-in email could not be sent. Try again shortly.",
                "code": "email_failed",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # Deliberately identical whether or not the address has an account: this
    # endpoint is unauthenticated, and a difference would enumerate the team.
    return Response(
        {
            "detail": "If that address can sign in, a link is on its way.",
            "expiresInMinutes": settings.MAGIC_LINK_TTL_MINUTES,
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny, CsrfProtected])
def verify_magic_link(request: Request) -> Response:
    serializer = MagicLinkVerifySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        user = consume_magic_link(serializer.validated_data["token"])
    except SignInError as exc:
        return Response(
            {"detail": exc.message, "code": exc.code},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Rotates the session key, so a session fixated before sign-in is useless.
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    get_token(request)
    return Response({"user": UserSerializer(user).data})


@api_view(["POST"])
@permission_classes([AllowAny, CsrfProtected])
def sign_out(request: Request) -> Response:
    logout(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([AllowAny])
def start_sso(request: Request, provider: str) -> Response:
    """Placeholder for the Entra ID / Google redirect flows.

    Answering 501 with the provider name keeps the button honest until the
    credentials exist; the sign-in screen disables it based on
    ``sign_in_options`` and never reaches this in normal use.
    """
    configured = {p.key: p for p in sso_provider_statuses()}
    known = configured.get(provider)
    if known is None:
        return Response(
            {"detail": f"Unknown sign-in provider '{provider}'.", "code": "unknown_provider"},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response(
        {
            "detail": (
                f"{known.label} sign-in is not configured yet. "
                "Add the client id and secret to the backend environment."
            ),
            "code": "provider_not_configured",
            "provider": provider,
        },
        status=status.HTTP_501_NOT_IMPLEMENTED,
    )
