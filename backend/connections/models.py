from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from . import crypto


class Provider(models.TextChoices):
    LINEAR = "linear", "Linear"
    JIRA = "jira", "Jira"
    AZURE_BOARDS = "azure_boards", "Azure Boards"
    AZURE_DEVOPS = "azure_devops", "Azure DevOps"
    GITHUB = "github", "GitHub"


class AuthMethod(models.TextChoices):
    API_KEY = "api_key", "API key"
    OAUTH = "oauth", "OAuth"


class ConnectionStatus(models.TextChoices):
    CONNECTED = "connected", "Connected"
    ERROR = "error", "Error"


class DiffScopeStrategy(models.TextChoices):
    """How a ticket is mapped to the code change that implements it.

    The agent needs exactly one diff per run. Get this wrong and every test case
    is generated against the wrong code, so it is an explicit setting rather
    than a guess. Tried in this order, falling through to asking the user.
    """

    LINKED_PR = "linked_pr", "The pull request linked on the ticket"
    BRANCH_NAME = "branch_name", "A branch whose name contains the ticket ID"
    MANUAL = "manual", "Ask me to pick a base and head each run"


class Connection(models.Model):
    """A credential for one third-party service, shared by the whole team.

    One row per provider: the workspace connects to Linear once and everybody
    uses it, which is what makes credentials revocable in a single place. If
    this ever needs to be multi-tenant, add a ``workspace`` foreign key and move
    the uniqueness onto ``(workspace, provider)``.
    """

    provider = models.CharField(max_length=32, choices=Provider.choices, unique=True)
    auth_method = models.CharField(
        max_length=16, choices=AuthMethod.choices, default=AuthMethod.API_KEY
    )

    # Encrypted at rest — see connections.crypto. Never serialise this field.
    encrypted_credential = models.TextField()
    # A recognisable stub such as "lin_api_...7Kd2". Safe to show; not reversible.
    credential_hint = models.CharField(max_length=64, blank=True)

    account_name = models.CharField(max_length=200, blank=True)
    account_email = models.EmailField(blank=True)
    organization_name = models.CharField(max_length=200, blank=True)
    organization_ref = models.CharField(max_length=200, blank=True)

    # Source-code providers only; ignored by Linear and friends. Lives per
    # connection because a GitHub org and an Azure org may genuinely differ in
    # whether their teams open pull requests before asking for tests.
    diff_scope_strategy = models.CharField(
        max_length=20,
        choices=DiffScopeStrategy.choices,
        default=DiffScopeStrategy.LINKED_PR,
    )

    status = models.CharField(
        max_length=16, choices=ConnectionStatus.choices, default=ConnectionStatus.CONNECTED
    )
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=400, blank=True)

    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="connections",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("provider",)

    def __str__(self) -> str:
        return f"{self.get_provider_display()} ({self.status})"

    # -- credential access -------------------------------------------------

    def set_credential(self, raw: str) -> None:
        self.encrypted_credential = crypto.encrypt(raw)
        self.credential_hint = crypto.hint_for(raw)

    @property
    def credential(self) -> str:
        """The decrypted credential. Server-side use only — never serialise it."""
        return crypto.decrypt(self.encrypted_credential)

    def mark_verified(self) -> None:
        self.status = ConnectionStatus.CONNECTED
        self.last_error = ""
        self.last_verified_at = timezone.now()

    def mark_failed(self, message: str) -> None:
        self.status = ConnectionStatus.ERROR
        self.last_error = message[:400]


class Repository(models.Model):
    """A repository visible to a source-code connection, and whether we use it.

    Nothing is cloned at connect time — the run pipeline clones into a throwaway
    container. ``last_indexed_commit`` stays empty until that first run, so the
    UI can tell the truth about what has actually been read.
    """

    connection = models.ForeignKey(
        Connection, on_delete=models.CASCADE, related_name="repositories"
    )
    external_id = models.CharField(max_length=128)
    name = models.CharField(max_length=200)
    project_name = models.CharField(max_length=200, blank=True)
    default_branch = models.CharField(max_length=200, blank=True)
    web_url = models.URLField(max_length=500, blank=True)
    remote_url = models.CharField(max_length=500, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)

    selected = models.BooleanField(default=False)
    last_indexed_commit = models.CharField(max_length=64, blank=True)
    last_indexed_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("project_name", "name")
        verbose_name_plural = "repositories"
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "external_id"], name="unique_repo_per_connection"
            )
        ]

    def __str__(self) -> str:
        return f"{self.project_name}/{self.name}" if self.project_name else self.name

    @property
    def is_indexed(self) -> bool:
        return bool(self.last_indexed_commit)


class LinearTeam(models.Model):
    """A team visible to the Linear connection, and whether we sync it.

    Kept as rows rather than a list of ids so the ticket picker in screen 04 can
    join against names and keys without another Linear round trip.
    """

    connection = models.ForeignKey(
        Connection, on_delete=models.CASCADE, related_name="linear_teams"
    )
    linear_id = models.CharField(max_length=64)
    key = models.CharField(max_length=32, blank=True)
    name = models.CharField(max_length=200)
    selected = models.BooleanField(default=False)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "linear_id"], name="unique_team_per_connection"
            )
        ]

    def __str__(self) -> str:
        return f"{self.key or '?'} · {self.name}"
