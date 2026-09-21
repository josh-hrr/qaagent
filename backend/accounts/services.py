"""Sign-in policy and the magic-link flow.

Kept out of the views so the rules are testable on their own and so the SSO
callbacks added later can reuse the same domain check and user provisioning.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone

from .models import MagicLinkToken, User


class SignInError(Exception):
    """Raised when a sign-in attempt is refused. ``code`` is API-facing."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --- policy ----------------------------------------------------------------


def email_domain_allowed(email: str) -> bool:
    """Who may sign in: a whole domain, or one exact address.

    An entry containing "@" matches that address and nothing else. This exists
    because the obvious workaround — adding ``gmail.com`` so one person can use
    their own account — would admit every Gmail user on earth.

    Empty ALLOWED_EMAIL_DOMAINS means anyone, which is the local-development
    default and what ``accounts.W001`` refuses to let pass quietly in
    production.
    """
    allowed = settings.ALLOWED_EMAIL_DOMAINS
    if not allowed:
        return True

    address = email.strip().lower()
    domain = address.rpartition("@")[2]
    for entry in allowed:
        if "@" in entry:
            if address == entry:
                return True
        elif domain == entry:
            return True
    return False


def client_ip(request) -> str | None:
    """The caller's address, used for rate limiting.

    X-Forwarded-For is only read when something in front of Django is known to
    set it (TRUST_PROXY_SSL_HEADER). Trusting it otherwise lets a caller invent
    a new address per request and walk straight past the per-IP limit.
    """
    if getattr(settings, "SECURE_PROXY_SSL_HEADER", None):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@dataclass(frozen=True)
class ProviderStatus:
    key: str
    label: str
    configured: bool


def sso_provider_statuses() -> list[ProviderStatus]:
    """A provider is offered only when its credentials are actually present."""
    statuses = []
    for key, cfg in settings.SSO_PROVIDERS.items():
        configured = bool(cfg.get("client_id")) and bool(cfg.get("client_secret"))
        statuses.append(ProviderStatus(key=key, label=cfg["label"], configured=configured))
    return statuses


# --- rate limiting ---------------------------------------------------------


def _recent(**filters) -> int:
    since = timezone.now() - timedelta(hours=1)
    return MagicLinkToken.objects.filter(created_at__gte=since, **filters).count()


def magic_link_rate_limited(email: str, ip: str | None) -> bool:
    """Guard against inbox flooding and blind token guessing.

    Counts issued links in the last hour, per address and per source IP. Backed
    by the token table rather than the cache so a restart cannot reset it.
    """
    if _recent(email=email.strip().lower()) >= settings.MAGIC_LINK_MAX_PER_EMAIL_PER_HOUR:
        return True
    if ip and _recent(requested_ip=ip) >= settings.MAGIC_LINK_MAX_PER_IP_PER_HOUR:
        return True
    return False


# --- magic link ------------------------------------------------------------


def send_magic_link(email: str, *, ip: str | None = None, user_agent: str = "") -> None:
    """Issue a link and email it.

    Callers must not reveal whether the address is known: the API answers the
    same way either way, so a stranger cannot enumerate the team from this
    endpoint.
    """
    email = email.strip().lower()

    # Invalidate anything still outstanding for this address — one live link at
    # a time means a forwarded older email cannot be replayed.
    MagicLinkToken.objects.usable().filter(email=email).update(consumed_at=timezone.now())

    token, raw_token = MagicLinkToken.issue(email, ip=ip, user_agent=user_agent)
    link = f"{settings.FRONTEND_URL}/auth/magic-link?token={quote(raw_token)}"
    minutes = settings.MAGIC_LINK_TTL_MINUTES

    send_mail(
        subject="Your QA Agent sign-in link",
        message=(
            "Use the link below to sign in to QA Agent.\n\n"
            f"{link}\n\n"
            f"It works once and expires in {minutes} minutes. "
            "If you did not ask for it you can ignore this email — "
            "nobody can sign in without opening the link.\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )


def consume_magic_link(raw_token: str) -> User:
    """Validate a link and return the user it signs in, provisioning on first use.

    Raises :class:`SignInError` with a code the frontend can branch on:
    ``invalid`` (unknown), ``expired``, ``already_used``, ``domain_not_allowed``.
    """
    token_hash = MagicLinkToken.hash_token(raw_token.strip())
    token = MagicLinkToken.objects.filter(token_hash=token_hash).first()

    if token is None:
        raise SignInError("invalid", "This sign-in link is not valid.")
    if token.is_consumed:
        raise SignInError("already_used", "This sign-in link has already been used.")
    if token.is_expired:
        raise SignInError("expired", "This sign-in link has expired.")
    if not email_domain_allowed(token.email):
        token.consume()
        raise SignInError("domain_not_allowed", "This email domain cannot sign in.")

    user = provision_user(token.email)
    if not user.is_active:
        token.consume()
        raise SignInError("inactive", "This account has been deactivated.")

    token.consume()
    return user


def provision_user(email: str, *, full_name: str = "") -> User:
    """Fetch or create the account for an address that has proved ownership.

    Shared by the magic-link flow and, later, the SSO callbacks — both arrive
    holding a verified email and nothing else.
    """
    email = email.strip().lower()
    user, created = User.objects.get_or_create(
        email=email,
        defaults={"full_name": full_name, "is_active": True},
    )
    if not created and full_name and not user.full_name:
        user.full_name = full_name
        user.save(update_fields=["full_name"])
    return user


def purge_stale_tokens() -> int:
    """Delete tokens that can no longer be used. Safe to call from a cron job."""
    cutoff = timezone.now() - timedelta(days=7)
    deleted, _ = MagicLinkToken.objects.filter(
        Q(consumed_at__isnull=False) | Q(expires_at__lt=timezone.now()),
        created_at__lt=cutoff,
    ).delete()
    return deleted
