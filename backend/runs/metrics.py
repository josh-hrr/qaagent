"""What the run history can honestly say about the product.

Every number here is counted from rows the app already writes, so it holds up
to being questioned: how many tickets went through, what came out, how much a
reviewer changed, and what it cost. Nothing is modelled or extrapolated.

The one thing this cannot know is how long the same work would have taken by
hand. That number decides the ROI story, and it has to come from the team
rather than from here — see ``docs/`` for where to record it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from .models import Ambiguity, ExportRecord, Finding, Run, RunStatus, TestCase, TestCaseStatus


def _percent(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


@dataclass
class Period:
    label: str
    runs: int = 0
    succeeded: int = 0
    cases: int = 0
    cost: Decimal = Decimal("0")


@dataclass
class Metrics:
    since: datetime | None
    generated_at: datetime

    runs_total: int = 0
    runs_succeeded: int = 0
    runs_failed: int = 0
    runs_cancelled: int = 0
    tickets_covered: int = 0
    success_rate: float = 0.0
    median_seconds: int = 0

    cases_total: int = 0
    cases_per_run: float = 0.0
    cases_approved: int = 0
    cases_rejected: int = 0
    cases_edited: int = 0
    approval_rate: float = 0.0
    rejection_rate: float = 0.0
    edit_rate: float = 0.0

    findings_total: int = 0
    findings_dismissed: int = 0
    findings_kept_rate: float = 0.0
    findings_to_cases: int = 0

    questions_total: int = 0
    questions_answered: int = 0

    exports_total: int = 0
    cases_exported: int = 0

    cost_total: Decimal = Decimal("0")
    cost_per_run: Decimal = Decimal("0")
    cost_per_kept_case: Decimal = Decimal("0")

    coverage_average: float = 0.0
    weekly: list[Period] = field(default_factory=list)


def _median_duration(runs) -> int:
    durations = [
        int((run.finished_at - run.started_at).total_seconds())
        for run in runs
        if run.started_at and run.finished_at
    ]
    if not durations:
        return 0
    durations.sort()
    middle = len(durations) // 2
    if len(durations) % 2:
        return durations[middle]
    return (durations[middle - 1] + durations[middle]) // 2


def _coverage(runs) -> float:
    """Average share of acceptance criteria a run's cases trace to."""
    import re

    shares = []
    for run in runs:
        criteria = {c["key"].upper() for c in (run.snapshot or {}).get("criteria", [])}
        if not criteria:
            continue
        traced = {
            match.upper()
            for traces in run.test_cases.values_list("traces_to", flat=True)
            for trace in traces
            for match in re.findall(r"\bAC-\d+\b", str(trace), re.I)
        }
        shares.append(len(criteria & traced) / len(criteria))
    return round(100 * sum(shares) / len(shares), 1) if shares else 0.0


def collect(since: datetime | None = None, weeks: int = 8) -> Metrics:
    runs = Run.objects.all()
    if since:
        runs = runs.filter(created_at__gte=since)

    by_status = dict(runs.values_list("status").annotate(n=Count("id")))
    succeeded = runs.filter(status=RunStatus.SUCCEEDED)

    cases = TestCase.objects.filter(run__in=runs)
    case_counts = cases.aggregate(
        total=Count("id"),
        approved=Count("id", filter=Q(status=TestCaseStatus.APPROVED)),
        rejected=Count("id", filter=Q(status=TestCaseStatus.REJECTED)),
        edited=Count("id", filter=Q(edited=True)),
    )
    total_cases = case_counts["total"] or 0
    # A kept case is one a reviewer did not throw out — the honest denominator
    # for "what did a usable test case cost".
    kept = total_cases - (case_counts["rejected"] or 0)

    findings = Finding.objects.filter(run__in=runs)
    finding_counts = findings.aggregate(
        total=Count("id"),
        dismissed=Count("id", filter=Q(dismissed=True)),
        converted=Count("id", filter=Q(test_case_number__isnull=False)),
    )

    questions = Ambiguity.objects.filter(run__in=runs)
    question_counts = questions.aggregate(
        total=Count("id"), answered=Count("id", filter=~Q(answer=""))
    )

    exports = ExportRecord.objects.filter(run__in=runs)
    cost_total = runs.aggregate(total=Sum("cost_usd"))["total"] or Decimal("0")
    runs_total = runs.count()

    metrics = Metrics(
        since=since,
        generated_at=timezone.now(),
        runs_total=runs_total,
        runs_succeeded=by_status.get(RunStatus.SUCCEEDED, 0),
        runs_failed=by_status.get(RunStatus.FAILED, 0),
        runs_cancelled=by_status.get(RunStatus.CANCELLED, 0),
        tickets_covered=runs.values("ticket_linear_id").distinct().count(),
        success_rate=_percent(by_status.get(RunStatus.SUCCEEDED, 0), runs_total),
        median_seconds=_median_duration(succeeded),
        cases_total=total_cases,
        cases_per_run=round(total_cases / succeeded.count(), 1) if succeeded.count() else 0.0,
        cases_approved=case_counts["approved"] or 0,
        cases_rejected=case_counts["rejected"] or 0,
        cases_edited=case_counts["edited"] or 0,
        approval_rate=_percent(case_counts["approved"] or 0, total_cases),
        rejection_rate=_percent(case_counts["rejected"] or 0, total_cases),
        edit_rate=_percent(case_counts["edited"] or 0, total_cases),
        findings_total=finding_counts["total"] or 0,
        findings_dismissed=finding_counts["dismissed"] or 0,
        findings_kept_rate=_percent(
            (finding_counts["total"] or 0) - (finding_counts["dismissed"] or 0), finding_counts["total"] or 0
        ),
        findings_to_cases=finding_counts["converted"] or 0,
        questions_total=question_counts["total"] or 0,
        questions_answered=question_counts["answered"] or 0,
        exports_total=exports.count(),
        cases_exported=sum(len(record.case_numbers) for record in exports),
        cost_total=cost_total,
        cost_per_run=round(cost_total / runs_total, 4) if runs_total else Decimal("0"),
        cost_per_kept_case=round(cost_total / kept, 4) if kept else Decimal("0"),
        coverage_average=_coverage(succeeded),
    )

    # Trend: one row per week, oldest first, so a chart can be drawn from it.
    now = timezone.now()
    for index in range(weeks - 1, -1, -1):
        end = now - timedelta(weeks=index)
        start = end - timedelta(weeks=1)
        window = runs.filter(created_at__gte=start, created_at__lt=end)
        metrics.weekly.append(
            Period(
                label=start.date().isoformat(),
                runs=window.count(),
                succeeded=window.filter(status=RunStatus.SUCCEEDED).count(),
                cases=TestCase.objects.filter(run__in=window).count(),
                cost=window.aggregate(total=Sum("cost_usd"))["total"] or Decimal("0"),
            )
        )
    return metrics


def per_run_rows(since: datetime | None = None) -> list[dict]:
    """One row per run, for a spreadsheet. No ticket text, only identifiers."""
    runs = Run.objects.all()
    if since:
        runs = runs.filter(created_at__gte=since)

    rows = []
    for run in runs.order_by("created_at").annotate(
        case_count=Count("test_cases", distinct=True),
        finding_count=Count("findings", distinct=True),
        question_count=Count("ambiguities", distinct=True),
        file_count=Count("files_read", distinct=True),
    ):
        seconds = (
            int((run.finished_at - run.started_at).total_seconds())
            if run.started_at and run.finished_at
            else ""
        )
        rows.append(
            {
                "run": run.pk,
                "ticket": run.ticket_identifier,
                "status": run.status,
                "created": run.created_at.date().isoformat(),
                "seconds": seconds,
                "model": run.model,
                "cost_usd": str(run.cost_usd),
                "files_read": run.file_count,
                "cases": run.case_count,
                "approved": run.test_cases.filter(status=TestCaseStatus.APPROVED).count(),
                "rejected": run.test_cases.filter(status=TestCaseStatus.REJECTED).count(),
                "edited": run.test_cases.filter(edited=True).count(),
                "findings": run.finding_count,
                "questions": run.question_count,
                "exports": run.exports.count(),
                "stopped_early": run.stopped_early,
            }
        )
    return rows
