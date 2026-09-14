"""A generation run and everything it produced.

A run is the unit of reproducibility: it records exactly which ticket content
and which code it read, so screen 06 can show *why* a test case exists and
later detect that the ticket moved on since.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class RunStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


TERMINAL_STATUSES = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}


class Stage(models.TextChoices):
    """Pipeline stages, in order. Mirrors the run screen in the design."""

    FETCH_TICKET = "fetch_ticket", "Fetch ticket context"
    RESOLVE_SCOPE = "resolve_scope", "Resolve diff scope"
    READ_CHANGES = "read_changes", "Read the changed files"
    GENERATE = "generate", "Draft test cases"
    CROSS_CHECK = "cross_check", "Cross-check and flag"


STAGE_ORDER = [s.value for s in Stage]


class Run(models.Model):
    ticket_identifier = models.CharField(max_length=40, db_index=True)
    ticket_linear_id = models.CharField(max_length=64)
    ticket_title = models.CharField(max_length=300, blank=True)
    ticket_url = models.URLField(max_length=500, blank=True)

    status = models.CharField(max_length=16, choices=RunStatus.choices, default=RunStatus.QUEUED)
    stage = models.CharField(max_length=20, choices=Stage.choices, blank=True)
    error_code = models.CharField(max_length=60, blank=True)
    error_message = models.TextField(blank=True)

    # --- snapshot: exactly what this run was built from ------------------
    # Stored so a later visit can tell whether the ticket changed since. The
    # hash covers only content that affects tests (description, criteria,
    # PRs) — not assignee, labels or status, which Linear also bumps
    # updatedAt for.
    snapshot = models.JSONField(default=dict, blank=True)
    snapshot_hash = models.CharField(max_length=64, blank=True, db_index=True)

    # --- scope -----------------------------------------------------------
    diff_scope_strategy = models.CharField(max_length=20, blank=True)
    # Pull requests actually used, and those skipped with the reason why.
    pull_requests = models.JSONField(default=list, blank=True)
    skipped_pull_requests = models.JSONField(default=list, blank=True)
    # Branches used when no pull request was linked (branch matching).
    branches = models.JSONField(default=list, blank=True)

    # --- model usage and cost -------------------------------------------
    model = models.CharField(max_length=60, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    cost_cap_usd = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    # True when a bound (files, rounds, spend) cut the agent short. A reviewer
    # needs to know coverage was truncated rather than complete.
    stopped_early = models.BooleanField(default=False)
    stopped_early_reason = models.CharField(max_length=200, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="runs"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cancel_requested = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.ticket_identifier} run {self.pk} ({self.status})"

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class RunEvent(models.Model):
    """A line in the run log. Plain text, safe to show a user."""

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="events")
    stage = models.CharField(max_length=20, choices=Stage.choices)
    message = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("id",)


class FileSource(models.TextChoices):
    DIFF = "diff", "Changed in the pull request"
    AGENT = "agent", "Requested by the agent"


class FileRead(models.Model):
    """One file the run read, and why — the backbone of traceability.

    See docs/decisions/0001-scope-expansion.md: every file enters scope either
    because the diff changed it, or because the agent asked for it with a
    stated reason.
    """

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="files_read")
    repository = models.CharField(max_length=200)
    path = models.CharField(max_length=1000)
    source = models.CharField(max_length=10, choices=FileSource.choices)
    reason = models.CharField(max_length=500, blank=True)
    change_type = models.CharField(max_length=20, blank=True)
    lines_added = models.PositiveIntegerField(default=0)
    lines_removed = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("id",)


class Priority(models.TextChoices):
    P1 = "P1", "P1"
    P2 = "P2", "P2"
    P3 = "P3", "P3"


class TestCaseStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    READY = "ready", "Ready"
    NEEDS_INFO = "needs_info", "Needs info"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class TestCase(models.Model):
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="test_cases")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    preconditions = models.TextField(blank=True)
    steps = models.JSONField(default=list)
    expected_result = models.TextField(blank=True)
    actual_result = models.TextField(blank=True)
    priority = models.CharField(max_length=2, choices=Priority.choices, default=Priority.P2)
    test_type = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=12, choices=TestCaseStatus.choices, default=TestCaseStatus.DRAFT)
    # Acceptance-criterion keys and "path:line" references this case came from.
    traces_to = models.JSONField(default=list, blank=True)
    suite = models.CharField(max_length=120, blank=True)
    estimate_minutes = models.PositiveSmallIntegerField(null=True, blank=True)

    # Where the case came from, and whether a person has changed it since.
    origin = models.CharField(max_length=12, default="generated")  # generated | finding | manual
    edited = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("number",)
        constraints = [models.UniqueConstraint(fields=["run", "number"], name="unique_case_number_per_run")]

    @property
    def identifier(self) -> str:
        return f"TC-{self.number:03d}"


class Severity(models.TextChoices):
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class Finding(models.Model):
    """Something in the code that looks wrong, independent of the test cases."""

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="findings")
    severity = models.CharField(max_length=8, choices=Severity.choices)
    title = models.CharField(max_length=300)
    explanation = models.TextField()
    location = models.CharField(max_length=500, blank=True)
    dismissed = models.BooleanField(default=False)
    # Set when a reviewer turns this finding into a test case.
    test_case_number = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ("id",)


class Ambiguity(models.Model):
    """A question the ticket does not answer, which blocks confident testing."""

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="ambiguities")
    kind = models.CharField(max_length=20)  # conflict | unspecified | untestable
    question = models.CharField(max_length=500)
    explanation = models.TextField(blank=True)
    source = models.CharField(max_length=300, blank=True)
    blocks_test_cases = models.JSONField(default=list, blank=True)

    # A reviewer's answer. Fed into the next run for the same ticket as a
    # clarification, so re-running actually uses what was decided.
    answer = models.TextField(blank=True)
    answered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("id",)
