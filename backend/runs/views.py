from __future__ import annotations

import logging
import re
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from .models import STAGE_ORDER, TERMINAL_STATUSES, Run, RunStatus, Stage
from .tasks import execute_run

log = logging.getLogger(__name__)


class StartRunSerializer(serializers.Serializer):
    # Only the ticket's id travels from the browser. Title, description and PRs
    # are read server-side when the run starts — client-supplied ticket content
    # could be stale or tampered with, and the snapshot must reflect Linear.
    ticketId = serializers.CharField(max_length=64)
    identifier = serializers.CharField(max_length=40, required=False, allow_blank=True)


def _criteria_coverage(run: Run) -> dict:
    """How many acceptance criteria at least one test case traces to.

    ``criteriaCovered`` stays None until test cases exist: during a run the
    number is unknown, and the UI shows "— / N" rather than a misleading 0.
    """
    total = len((run.snapshot or {}).get("criteria") or [])
    if not run.test_cases.exists():
        return {"criteriaTotal": total, "criteriaCovered": None}
    keys = {c["key"].upper() for c in run.snapshot.get("criteria", [])}
    traced = {
        match.upper()
        for traces in run.test_cases.values_list("traces_to", flat=True)
        for trace in traces
        for match in re.findall(r"\bAC-\d+\b", str(trace), re.I)
    }
    return {"criteriaTotal": total, "criteriaCovered": len(keys & traced)}


def monthly_spend() -> dict:
    """What the workspace has spent this calendar month, against its cap.

    Counted from the runs themselves rather than a running total, so it stays
    right after a run is deleted and cannot drift.
    """
    now = timezone.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month = Run.objects.filter(created_at__gte=start)
    spent = month.aggregate(total=Sum("cost_usd"))["total"] or Decimal("0")
    cap = Decimal(str(settings.WORKSPACE_MONTHLY_CAP_USD))
    return {
        "spentUsd": str(spent.quantize(Decimal("0.0001"))),
        "capUsd": str(cap),
        "runCount": month.count(),
        "model": settings.LLM_MODEL,
        "capReached": cap > 0 and spent >= cap,
    }


def _serialize(run: Run, *, detail: bool) -> dict:
    stage_index = STAGE_ORDER.index(run.stage) if run.stage in STAGE_ORDER else -1
    stages = []
    for index, value in enumerate(STAGE_ORDER):
        if run.status == RunStatus.SUCCEEDED or index < stage_index:
            state = "done"
        elif index == stage_index:
            state = {
                RunStatus.RUNNING: "running",
                RunStatus.FAILED: "failed",
                RunStatus.CANCELLED: "cancelled",
            }.get(run.status, "queued")
        else:
            state = "skipped" if run.status in (RunStatus.FAILED, RunStatus.CANCELLED) else "queued"
        stages.append({"key": value, "label": Stage(value).label, "state": state})

    body = {
        "id": run.pk,
        "ticketIdentifier": run.ticket_identifier,
        "ticketTitle": run.ticket_title,
        "ticketUrl": run.ticket_url,
        "status": run.status,
        "stage": run.stage,
        "stages": stages,
        "errorCode": run.error_code,
        "errorMessage": run.error_message,
        "model": run.model,
        "costUsd": str(run.cost_usd),
        "costCapUsd": str(run.cost_cap_usd),
        "stoppedEarly": run.stopped_early,
        "stoppedEarlyReason": run.stopped_early_reason,
        "createdAt": run.created_at.isoformat(),
        "startedAt": run.started_at.isoformat() if run.started_at else None,
        "finishedAt": run.finished_at.isoformat() if run.finished_at else None,
        "isTerminal": run.status in TERMINAL_STATUSES,
        "counts": {
            "testCases": run.test_cases.count(),
            "findings": run.findings.count(),
            "ambiguities": run.ambiguities.count(),
            "filesRead": run.files_read.count(),
            **_criteria_coverage(run),
        },
    }
    if detail:
        body.update(
            {
                "snapshotHash": run.snapshot_hash,
                "pullRequests": run.pull_requests,
                "skippedPullRequests": run.skipped_pull_requests,
                "tokens": {
                    "input": run.input_tokens,
                    "output": run.output_tokens,
                    "cacheRead": run.cache_read_tokens,
                    "cacheWrite": run.cache_write_tokens,
                },
                "events": [
                    {"stage": e.stage, "message": e.message, "at": e.created_at.isoformat()}
                    for e in run.events.all()
                ],
                "filesRead": [
                    {
                        "repository": f.repository,
                        "path": f.path,
                        "source": f.source,
                        "reason": f.reason,
                        "changeType": f.change_type,
                        "linesAdded": f.lines_added,
                        "linesRemoved": f.lines_removed,
                    }
                    for f in run.files_read.all()
                ],
            }
        )
    return body


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_run(request: Request) -> Response:
    serializer = StartRunSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    ticket_id = serializer.validated_data["ticketId"]

    spend = monthly_spend()
    if spend["capReached"]:
        return Response(
            {
                "detail": (
                    f"This workspace has spent ${spend['spentUsd']} of its ${spend['capUsd']} "
                    "cap for the month. Raise WORKSPACE_MONTHLY_CAP_USD to run more."
                ),
                "code": "monthly_cap_reached",
                "spend": spend,
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    with transaction.atomic():
        # One active run per ticket. A double-click or a second tab should land
        # on the run already in progress, not pay for two identical runs.
        active = (
            Run.objects.select_for_update()
            .filter(ticket_linear_id=ticket_id)
            .exclude(status__in=TERMINAL_STATUSES)
            .first()
        )
        if active:
            return Response({"run": _serialize(active, detail=False), "existing": True}, status=status.HTTP_200_OK)

        run = Run.objects.create(
            ticket_linear_id=ticket_id,
            ticket_identifier=serializer.validated_data.get("identifier", "")[:40],
            created_by=request.user,
        )
        # Enqueue only once the row is committed, or a fast worker could look
        # for a run that does not exist yet.
        transaction.on_commit(lambda: execute_run.enqueue(run.pk))

    log.info("Run %s queued for %s by %s", run.pk, ticket_id, request.user.email)
    return Response({"run": _serialize(run, detail=False), "existing": False}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def run_detail(request: Request, run_id: int) -> Response:
    run = get_object_or_404(Run, pk=run_id)
    return Response({"run": _serialize(run, detail=True)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cancel_run(request: Request, run_id: int) -> Response:
    run = get_object_or_404(Run, pk=run_id)
    if run.is_terminal:
        return Response(
            {"detail": "This run has already finished.", "code": "already_finished"},
            status=status.HTTP_409_CONFLICT,
        )
    # A flag, not a kill: the worker checks it between stages and model rounds,
    # so a run stops at a clean boundary instead of mid-write.
    Run.objects.filter(pk=run.pk).update(cancel_requested=True)
    if run.status == RunStatus.QUEUED:
        Run.objects.filter(pk=run.pk, status=RunStatus.QUEUED).update(status=RunStatus.CANCELLED)
    run.refresh_from_db()
    return Response({"run": _serialize(run, detail=False)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_runs(request: Request) -> Response:
    runs = Run.objects.all()
    ticket = request.query_params.get("ticketId")
    if ticket:
        runs = runs.filter(ticket_linear_id=ticket)
    return Response(
        {
            "runs": [_serialize(run, detail=False) for run in runs[:50]],
            # For the "N live" badge in the navigation rail.
            "activeCount": Run.objects.exclude(status__in=TERMINAL_STATUSES).count(),
            "spend": monthly_spend(),
        }
    )
