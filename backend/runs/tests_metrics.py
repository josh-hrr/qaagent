"""Numbers quoted to other people have to be countable from the rows."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import User

from .metrics import collect, per_run_rows
from .models import Ambiguity, ExportRecord, Finding, Run, RunStatus, TestCaseStatus
from .models import TestCase as GeneratedCase


class MetricsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dev@example.com")
        started = timezone.now() - timedelta(minutes=5)

        self.run = Run.objects.create(
            ticket_linear_id="lin_1",
            ticket_identifier="TES-8",
            status=RunStatus.SUCCEEDED,
            cost_usd=Decimal("0.05"),
            snapshot={"criteria": [{"key": "AC-1", "text": "x"}, {"key": "AC-2", "text": "y"}]},
        )
        Run.objects.filter(pk=self.run.pk).update(
            started_at=started, finished_at=started + timedelta(seconds=90)
        )

        for number, status_value, edited, traces in [
            (1, TestCaseStatus.APPROVED, False, ["AC-1"]),
            (2, TestCaseStatus.APPROVED, True, ["AC-1"]),
            (3, TestCaseStatus.REJECTED, False, []),
            (4, TestCaseStatus.DRAFT, False, []),
        ]:
            GeneratedCase.objects.create(
                run=self.run, number=number, title=f"Case {number}", status=status_value,
                edited=edited, traces_to=traces,
            )

        Finding.objects.create(run=self.run, severity="high", title="A", explanation="x")
        Finding.objects.create(run=self.run, severity="low", title="B", explanation="x", dismissed=True)
        Finding.objects.create(run=self.run, severity="low", title="C", explanation="x", test_case_number=4)
        Ambiguity.objects.create(run=self.run, kind="unspecified", question="Q1", answer="Yes")
        Ambiguity.objects.create(run=self.run, kind="unspecified", question="Q2")
        ExportRecord.objects.create(
            run=self.run, exported_by=self.user, file_format="csv", scope="all",
            case_numbers=[1, 2], filename="x.csv", byte_size=100,
        )

        # A second run that failed, so the rates have something to divide by.
        Run.objects.create(ticket_linear_id="lin_2", ticket_identifier="TES-9", status=RunStatus.FAILED)

    def test_throughput(self):
        m = collect()
        self.assertEqual((m.runs_total, m.runs_succeeded, m.runs_failed), (2, 1, 1))
        self.assertEqual(m.tickets_covered, 2)
        self.assertEqual(m.success_rate, 50.0)
        self.assertEqual(m.median_seconds, 90)

    def test_review_outcomes_are_the_quality_signal(self):
        m = collect()
        self.assertEqual(m.cases_total, 4)
        self.assertEqual((m.cases_approved, m.cases_rejected, m.cases_edited), (2, 1, 1))
        self.assertEqual(m.approval_rate, 50.0)
        self.assertEqual(m.rejection_rate, 25.0)
        self.assertEqual(m.edit_rate, 25.0)
        # One of two criteria traced by at least one case.
        self.assertEqual(m.coverage_average, 50.0)

    def test_findings_and_questions(self):
        m = collect()
        self.assertEqual((m.findings_total, m.findings_dismissed), (3, 1))
        self.assertEqual(m.findings_kept_rate, 66.7)
        self.assertEqual(m.findings_to_cases, 1)
        self.assertEqual((m.questions_total, m.questions_answered), (2, 1))

    def test_cost_is_divided_by_cases_a_reviewer_kept(self):
        m = collect()
        self.assertEqual(m.cost_total, Decimal("0.05"))
        self.assertEqual(m.cost_per_run, Decimal("0.0250"))
        # 3 kept cases out of 4 generated: 0.05 / 3.
        self.assertEqual(m.cost_per_kept_case, Decimal("0.0167"))

    def test_exports_count_the_cases_handed_on(self):
        m = collect()
        self.assertEqual((m.exports_total, m.cases_exported), (1, 2))

    def test_since_excludes_older_runs(self):
        Run.objects.filter(pk=self.run.pk).update(created_at=timezone.now() - timedelta(days=60))
        m = collect(since=timezone.now() - timedelta(days=7))
        self.assertEqual(m.runs_total, 1)
        self.assertEqual(m.cases_total, 0)

    def test_weekly_trend_ends_with_this_week(self):
        m = collect(weeks=4)
        self.assertEqual(len(m.weekly), 4)
        self.assertEqual(m.weekly[-1].runs, 2)
        self.assertEqual(m.weekly[0].runs, 0)

    def test_per_run_rows_carry_no_ticket_text(self):
        rows = per_run_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["ticket"], "TES-8")
        self.assertEqual(rows[0]["cases"], 4)
        self.assertEqual(rows[0]["approved"], 2)
        self.assertNotIn("title", rows[0])
        self.assertNotIn("snapshot", rows[0])

    def test_command_prints_a_report(self):
        out = StringIO()
        call_command("qa_metrics", stdout=out)
        printed = out.getvalue()
        self.assertIn("Throughput", printed)
        self.assertIn("per kept test case", printed)
        self.assertIn("Time saved is not measured here", printed)

    def test_command_writes_a_spreadsheet(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "metrics.csv"
            call_command("qa_metrics", csv=str(target), stdout=StringIO())
            lines = target.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 3)  # header plus two runs
        self.assertIn("cost_usd", lines[0])

    def test_command_is_quiet_with_no_runs(self):
        Run.objects.all().delete()
        out = StringIO()
        call_command("qa_metrics", stdout=out)
        self.assertIn("No runs yet", out.getvalue())
