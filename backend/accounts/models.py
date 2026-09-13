from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """Manager for a user model keyed on email rather than a username."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        if password:
            user.set_password(password)
        else:
            # Sign-in happens through SSO or a magic link; there is no password
            # to check, and an unusable one cannot be brute-forced.
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        if extra.get("is_staff") is not True:
            raise ValueError("A superuser must have is_staff=True.")
        if extra.get("is_superuser") is not True:
            raise ValueError("A superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """Workspace member. Email is the identifier; there is no username."""

    username = None  # type: ignore[assignment]
    email = models.EmailField("email address", unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    avatar_url = models.URLField(blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        ordering = ("email",)

    def __str__(self) -> str:
        return self.email

    @property
    def display_name(self) -> str:
        return self.full_name or self.email.split("@")[0]

    @property
    def initials(self) -> str:
        source = self.full_name.strip() or self.email.split("@")[0]
        parts = [p for p in source.replace(".", " ").replace("_", " ").split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()


class MagicLinkTokenQuerySet(models.QuerySet):
    def usable(self):
        return self.filter(consumed_at__isnull=True, expires_at__gt=timezone.now())


class MagicLinkToken(models.Model):
    """A single-use sign-in link.

    Only the SHA-256 hash of the token is stored, so a database leak does not
    hand out working links. The raw value exists once, in the email.
    """

    email = models.EmailField(db_index=True)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)
    requested_user_agent = models.CharField(max_length=400, blank=True)

    objects = MagicLinkTokenQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["email", "created_at"])]

    def __str__(self) -> str:
        return f"magic link for {self.email}"

    # -- lifecycle ---------------------------------------------------------

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @classmethod
    def issue(
        cls,
        email: str,
        *,
        ip: str | None = None,
        user_agent: str = "",
    ) -> tuple["MagicLinkToken", str]:
        """Create a token and return it alongside the raw value to email."""
        email = email.strip().lower()
        raw_token = secrets.token_urlsafe(32)
        ttl = timedelta(minutes=settings.MAGIC_LINK_TTL_MINUTES)
        token = cls.objects.create(
            email=email,
            token_hash=cls.hash_token(raw_token),
            expires_at=timezone.now() + ttl,
            requested_ip=ip,
            requested_user_agent=user_agent[:400],
        )
        return token, raw_token

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    def consume(self) -> None:
        self.consumed_at = timezone.now()
        self.save(update_fields=["consumed_at"])
