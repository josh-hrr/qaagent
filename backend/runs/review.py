"""Screen 06: review what a run produced, and tell whether it is still current.

Everything here reads or edits our own database, except the drift check,
which asks Linear and Azure DevOps what changed since the run. That check
runs when the page opens and when a reviewer asks, never on a timer.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote, urlencode

from django.db import transaction
from django.db.models import Max, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from connections.azure import AzureError
from connections.linear import LinearError
from connections.models import Connection, Provider, Repository
from tickets.criteria import extract_criteria
from tickets.linear_issues import fetch_issue

from .azure_code import CodeReader
from .models import (
    Ambiguity,
    FileSource,
    Finding,
    Priority,
    Run,
    RunStatus,
    TestCase,
    TestCaseStatus,
)
from .scope import snapshot_hash
from .views import _criteria_coverage

log = logging.getLogger(__name__)

SEVERITY_PRIORITY = {"high": Priority.P1, "medium": Priority.P2, "low": Priority.P3}
CRITERION_RE = re.compile(r"^AC-\d+$", re.I)
# "/src/auth.py:42", "src/auth.py:42-50" or just a path.
LOCATION_RE = re.compile(r"^(?P<path>[^\s:]+?)(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?$")


# --- helpers ---------------------------------------------------------------


def _reviewable(run_id: int) -> Run:
    return get_object_or_404(Run, pk=run_id)


def _not_editable(run: Run) -> Response | None:
    if run.status != RunStatus.SUCCEEDED:
        return Response(
            {"detail": "Only a finished run can be reviewed.", "code": "run_not_finished"},
            status=status.HTTP_409_CONFLICT,
        )
    return None


def _default_branch(repository: str) -> str:
    repo = Repository.objects.filter(name__iexact=repository).first()
    return (repo.default_branch.removeprefix("refs/heads/") if repo and repo.default_branch else "")


def _scope(run: Run) -> dict | None:
    """The code the run read: its first pull request, or else its branch."""
    if run.pull_requests:
        pr = run.pull_requests[0]
        repository = pr.get("repository", "")
        return {
            "kind": "pull_request",
            "repository": repository,
            "sourceRef": pr.get("source_ref", ""),
            # Runs from before the refs were recorded still know where a PR
            # lands: the repository's default branch.
            "targetRef": pr.get("target_ref") or _default_branch(repository),
            "headCommit": pr.get("head_commit", ""),
            "baseCommit": pr.get("base_commit", ""),
            "number": pr.get("number"),
            "url": pr.get("url", ""),
        }
    if run.branches:
        branch = run.branches[0]
        return {
            "kind": "branch",
            "repository": branch.get("repository", ""),
            "sourceRef": branch.get("name", ""),
            "targetRef": branch.get("target_ref", ""),
            "headCommit": branch.get("head_commit", ""),
            "baseCommit": branch.get("base_commit", ""),
            "number": None,
            "url": branch.get("url", ""),
        }
    return None


def code_url(repo_web_url: str, head_commit: str, location: str) -> str:
    """A link to a file (and line) in Azure DevOps at the commit the run read.

    Pinned to the commit, not the branch: the line a finding points at should
    still be that line after someone pushes.
    """
    match = LOCATION_RE.match((location or "").strip())
    if not repo_web_url or not head_commit or not match:
        return ""
    path = "/" + match["path"].lstrip("/")
    params = {"path": path, "version": f"GC{head_commit}", "_a": "contents"}
    if match["start"]:
        params.update(
            line=match["start"], lineEnd=match["end"] or match["start"],
            lineStartColumn=1, lineEndColumn=1, lineStyle="plain",
        )
    return f"{repo_web_url}?{urlencode(params, quote_via=quote, safe='/')}"


class _Links:
    """Builds links for one run without a query per trace."""

    def __init__(self, run: Run):
        scope = _scope(run)
        self.head = scope["headCommit"] if scope else ""
        repo = (
            Repository.objects.filter(name__iexact=scope["repository"]).first() if scope else None
        )
        self.web_url = repo.web_url if repo else ""
        self.criteria = {c["key"].upper(): c["text"] for c in (run.snapshot or {}).get("criteria", [])}

    def code(self, location: str) -> str:
        return code_url(self.web_url, self.head, location)

    def trace(self, value: str) -> dict:
        key = value.strip()
        if CRITERION_RE.match(key):
            return {"label": key.upper(), "kind": "criterion", "text": self.criteria.get(key.upper(), ""), "url": ""}
        return {"label": key, "kind": "code", "text": "", "url": self.code(key)}


def _case(case: TestCase, links: _Links) -> dict:
    return {
        "number": case.number,
        "identifier": case.identifier,
        "title": case.title,
        "description": case.description,
        "preconditions": case.preconditions,
        "steps": case.steps,
        "expectedResult": case.expected_result,
        "actualResult": case.actual_result,
        "priority": case.priority,
        "testType": case.test_type,
        "status": case.status,
        "suite": case.suite,
        "estimateMinutes": case.estimate_minutes,
        "origin": case.origin,
        "edited": case.edited,
        "reviewedBy": case.reviewed_by.email if case.reviewed_by_id else None,
        "tracesTo": [links.trace(t) for t in case.traces_to],
    }


def _finding(finding: Finding, links: _Links) -> dict:
    return {
        "id": finding.pk,
        "severity": finding.severity,
        "title": finding.title,
        "explanation": finding.explanation,
        "location": finding.location,
        "locationUrl": links.code(finding.location),
        "dismissed": finding.dismissed,
        "testCaseNumber": finding.test_case_number,
    }


def _ambiguity(item: Ambiguity) -> dict:
    return {
        "id": item.pk,
        "kind": item.kind,
        "question": item.question,
        "explanation": item.explanation,
        "source": item.source,
        "blocksTestCases": item.blocks_test_cases,
        "answer": item.answer,
        "answeredBy": item.answered_by.email if item.answered_by_id else None,
        "answeredAt": item.answered_at.isoformat() if item.answered_at else None,
    }


def _header(run: Run) -> dict:
    diff = run.files_read.filter(source=FileSource.DIFF)
    totals = diff.aggregate(added=Sum("lines_added"), removed=Sum("lines_removed"))
    run_number = Run.objects.filter(ticket_linear_id=run.ticket_linear_id, pk__lte=run.pk).count()
    return {
        "id": run.pk,
        "runNumber": run_number,
        "status": run.status,
        "ticketIdentifier": run.ticket_identifier,
        "ticketTitle": run.ticket_title,
        "ticketUrl": run.ticket_url,
        "ticketLinearId": run.ticket_linear_id,
        "teamName": (run.snapshot or {}).get("team_name", ""),
        "createdAt": run.created_at.isoformat(),
        "finishedAt": run.finished_at.isoformat() if run.finished_at else None,
        "costUsd": str(run.cost_usd),
        "model": run.model,
        "stoppedEarly": run.stopped_early,
        "stoppedEarlyReason": run.stopped_early_reason,
        "scope": _scope(run),
        "diff": {
            "files": diff.values("repository", "path").distinct().count(),
            "linesAdded": totals["added"] or 0,
            "linesRemoved": totals["removed"] or 0,
        },
        "criteria": (run.snapshot or {}).get("criteria", []),
        **_criteria_coverage(run),
    }


def _all(run: Run) -> dict:
    links = _Links(run)
    cases = run.test_cases.select_related("reviewed_by")
    return {
        "run": _header(run),
        "testCases": [_case(c, links) for c in cases],
        "findings": [_finding(f, links) for f in run.findings.all()],
        "ambiguities": [_ambiguity(a) for a in run.ambiguities.select_related("answered_by")],
    }


# --- read ------------------------------------------------------------------


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def review(request: Request, run_id: int) -> Response:
    run = _reviewable(run_id)
    return Response(_all(run))


# --- test cases ------------------------------------------------------------


class TestCaseUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=300, required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=10_000)
    preconditions = serializers.CharField(required=False, allow_blank=True, max_length=10_000)
    steps = serializers.ListField(
        child=serializers.CharField(max_length=2_000, allow_blank=False), required=False, max_length=100
    )
    expectedResult = serializers.CharField(required=False, allow_blank=True, max_length=10_000)
    actualResult = serializers.CharField(required=False, allow_blank=True, max_length=10_000)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False)
    status = serializers.ChoiceField(choices=TestCaseStatus.choices, required=False)
    testType = serializers.CharField(max_length=30, required=False, allow_blank=True)
    suite = serializers.CharField(max_length=120, required=False, allow_blank=True)
    estimateMinutes = serializers.IntegerField(min_value=1, max_value=600, required=False, allow_null=True)


# Content a person rewrote — as opposed to triage (status, priority), which
# does not make the case "edited".
CONTENT_FIELDS = {
    "title": "title",
    "description": "description",
    "preconditions": "preconditions",
    "steps": "steps",
    "expectedResult": "expected_result",
    "testType": "test_type",
    "suite": "suite",
    "estimateMinutes": "estimate_minutes",
}
TRIAGE_FIELDS = {"priority": "priority", "status": "status", "actualResult": "actual_result"}


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def test_case(request: Request, run_id: int, number: int) -> Response:
    run = _reviewable(run_id)
    if blocked := _not_editable(run):
        return blocked
    case = get_object_or_404(TestCase, run=run, number=number)

    if request.method == "DELETE":
        case.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = TestCaseUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    changed = []
    for key, field in {**CONTENT_FIELDS, **TRIAGE_FIELDS}.items():
        if key in data and getattr(case, field) != data[key]:
            setattr(case, field, data[key])
            changed.append(field)
            if key in CONTENT_FIELDS:
                case.edited = True
    if "status" in data:
        case.reviewed_by = request.user
        changed.append("reviewed_by")
    if changed:
        case.save()
    return Response({"testCase": _case(case, _Links(run))})


class BulkSerializer(serializers.Serializer):
    numbers = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=1000)
    action = serializers.ChoiceField(choices=["set_priority", "set_status", "delete"])
    value = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        allowed = {"set_priority": Priority.values, "set_status": TestCaseStatus.values}.get(attrs["action"])
        if allowed is not None and attrs.get("value") not in allowed:
            raise serializers.ValidationError({"value": f"Must be one of: {', '.join(allowed)}."})
        return attrs


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def bulk_test_cases(request: Request, run_id: int) -> Response:
    run = _reviewable(run_id)
    if blocked := _not_editable(run):
        return blocked
    serializer = BulkSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    cases = TestCase.objects.filter(run=run, number__in=data["numbers"])
    if data["action"] == "delete":
        count, _ = cases.delete()
    elif data["action"] == "set_priority":
        count = cases.update(priority=data["value"], updated_at=timezone.now())
    else:
        count = cases.update(status=data["value"], reviewed_by=request.user, updated_at=timezone.now())
    return Response({"updated": count, **_all(run)})


# --- findings --------------------------------------------------------------


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def finding_to_test_case(request: Request, run_id: int, finding_id: int) -> Response:
    run = _reviewable(run_id)
    if blocked := _not_editable(run):
        return blocked

    with transaction.atomic():
        finding = get_object_or_404(Finding.objects.select_for_update(), run=run, pk=finding_id)
        if finding.test_case_number and TestCase.objects.filter(run=run, number=finding.test_case_number).exists():
            return Response(
                {"detail": "This finding already has a test case.", "code": "already_added"},
                status=status.HTTP_409_CONFLICT,
            )
        # Lock the run's row so two clicks cannot pick the same number.
        Run.objects.select_for_update().filter(pk=run.pk).first()
        number = (run.test_cases.aggregate(n=Max("number"))["n"] or 0) + 1
        case = TestCase.objects.create(
            run=run,
            number=number,
            title=f"Verify: {finding.title}"[:300],
            description=finding.explanation,
            priority=SEVERITY_PRIORITY.get(finding.severity, Priority.P2),
            test_type="negative",
            traces_to=[finding.location] if finding.location else [],
            origin="finding",
            status=TestCaseStatus.DRAFT,
        )
        finding.test_case_number = number
        finding.save(update_fields=["test_case_number"])

    return Response({"testCase": _case(case, _Links(run)), **_all(run)}, status=status.HTTP_201_CREATED)


class DismissSerializer(serializers.Serializer):
    dismissed = serializers.BooleanField(default=True)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def dismiss_finding(request: Request, run_id: int, finding_id: int) -> Response:
    run = _reviewable(run_id)
    if blocked := _not_editable(run):
        return blocked
    finding = get_object_or_404(Finding, run=run, pk=finding_id)
    serializer = DismissSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    finding.dismissed = serializer.validated_data["dismissed"]
    finding.save(update_fields=["dismissed"])
    return Response({"finding": _finding(finding, _Links(run))})


# --- ambiguities -----------------------------------------------------------


class AnswerSerializer(serializers.Serializer):
    answer = serializers.CharField(allow_blank=True, max_length=4_000, trim_whitespace=True)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def answer_ambiguity(request: Request, run_id: int, ambiguity_id: int) -> Response:
    run = _reviewable(run_id)
    if blocked := _not_editable(run):
        return blocked
    item = get_object_or_404(Ambiguity, run=run, pk=ambiguity_id)
    serializer = AnswerSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    item.answer = serializer.validated_data["answer"]
    item.answered_by = request.user if item.answer else None
    item.answered_at = timezone.now() if item.answer else None
    item.save(update_fields=["answer", "answered_by", "answered_at"])
    return Response({"ambiguity": _ambiguity(item)})


# --- drift -----------------------------------------------------------------


def _ticket_drift(run: Run) -> dict:
    linear = Connection.objects.filter(provider=Provider.LINEAR).first()
    if linear is None:
        return {"error": "Linear is not connected."}
    try:
        issue = fetch_issue(linear.credential, run.ticket_linear_id)
    except LinearError as exc:
        return {"error": exc.message}

    before = run.snapshot or {}
    live = {
        "title": issue.title,
        "description": issue.description,
        "criteria": [{"key": c.key, "text": c.text} for c in extract_criteria(issue.description)],
        "pull_request_urls": [p.url for p in issue.pull_requests],
    }
    changed = snapshot_hash(live) != run.snapshot_hash

    old_criteria = {c["key"]: c["text"] for c in before.get("criteria", [])}
    new_criteria = {c["key"]: c["text"] for c in live["criteria"]}
    old_prs, new_prs = set(before.get("pull_request_urls", [])), set(live["pull_request_urls"])
    return {
        "changed": changed,
        "updatedAt": issue.updated_at,
        "titleChanged": issue.title != before.get("title", ""),
        "descriptionChanged": (issue.description or "") != (before.get("description") or ""),
        "criteriaAdded": sorted(k for k in new_criteria if k not in old_criteria),
        "criteriaRemoved": sorted(k for k in old_criteria if k not in new_criteria),
        "criteriaEdited": sorted(k for k in new_criteria if k in old_criteria and new_criteria[k] != old_criteria[k]),
        "pullRequestsAdded": sorted(new_prs - old_prs),
        "pullRequestsRemoved": sorted(old_prs - new_prs),
    }


def _code_drift(run: Run) -> list[dict]:
    """Commits pushed to the run's PRs or branches since it read them."""
    source = Connection.objects.filter(provider=Provider.AZURE_DEVOPS).first()
    if source is None:
        return [{"error": "Azure DevOps is not connected."}]

    results = []
    for pr in run.pull_requests:
        label = f"PR #{pr.get('number')} in {pr.get('repository')}"
        try:
            reader = _reader(source, pr)
            info = reader.pull_request(pr["number"])
            ahead = reader.commits_ahead(pr.get("head_commit", ""), info.head_commit)
            results.append({"label": label, "headCommit": info.head_commit, "commitsAhead": ahead, "status": info.status})
        except (AzureError, KeyError) as exc:
            results.append({"label": label, "error": getattr(exc, "message", "Could not read the pull request.")})

    for branch in run.branches:
        label = f"{branch.get('name')} in {branch.get('repository')}"
        try:
            reader = _reader(source, branch)
            head = dict(reader.branches()).get(branch["name"], "")
            if not head:
                results.append({"label": label, "error": "The branch no longer exists."})
                continue
            ahead = reader.commits_ahead(branch.get("head_commit", ""), head)
            results.append({"label": label, "headCommit": head, "commitsAhead": ahead, "status": "branch"})
        except (AzureError, KeyError) as exc:
            results.append({"label": label, "error": getattr(exc, "message", "Could not read the branch.")})
    return results


def _reader(source: Connection, entry: dict) -> CodeReader:
    # Older runs did not store organization and project; the connected
    # repository row has them.
    repo = Repository.objects.filter(connection=source, name__iexact=entry.get("repository", "")).first()
    organization = entry.get("organization") or source.organization_name
    project = entry.get("project") or (repo.project_name if repo else "")
    return CodeReader(organization, project, entry["repository"], source.credential)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def drift(request: Request, run_id: int) -> Response:
    run = _reviewable(run_id)
    if run.status != RunStatus.SUCCEEDED:
        return Response({"ticket": None, "code": [], "checkedAt": timezone.now().isoformat()})
    return Response({"ticket": _ticket_drift(run), "code": _code_drift(run), "checkedAt": timezone.now().isoformat()})
