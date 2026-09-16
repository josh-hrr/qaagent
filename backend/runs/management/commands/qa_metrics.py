"""Print what the run history says, and optionally write it to a spreadsheet.

    python manage.py qa_metrics
    python manage.py qa_metrics --since 2026-01-01 --csv metrics.csv
"""

from __future__ import annotations

import csv
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ...metrics import collect, per_run_rows


def _minutes(seconds: int) -> str:
    if not seconds:
        return "-"
    return f"{seconds // 60}m {seconds % 60}s" if seconds >= 60 else f"{seconds}s"


class Command(BaseCommand):
    help = "Summarise runs, review outcomes and cost."

    def add_arguments(self, parser):
        parser.add_argument("--since", help="Only count runs created on or after this date (YYYY-MM-DD).")
        parser.add_argument("--csv", help="Also write one row per run to this file.")
        parser.add_argument("--weeks", type=int, default=8, help="How many weeks of trend to show.")

    def handle(self, *args, **options):
        since = None
        if options["since"]:
            try:
                since = timezone.make_aware(datetime.strptime(options["since"], "%Y-%m-%d"))
            except ValueError as exc:
                raise CommandError("--since must look like 2026-01-01.") from exc

        m = collect(since=since, weeks=options["weeks"])
        if m.runs_total == 0:
            self.stdout.write("No runs yet - nothing to report.")
            return

        def line(label: str, value: str, note: str = "") -> None:
            self.stdout.write(f"  {label:<26}{value:<18}{note}")

        window = f"since {since.date()}" if since else "all time"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nQA Agent - {window}"))

        self.stdout.write(self.style.MIGRATE_LABEL("\nThroughput"))
        line("runs", str(m.runs_total), f"{m.tickets_covered} distinct tickets")
        line("succeeded", str(m.runs_succeeded), f"{m.success_rate}% of runs")
        line("failed / cancelled", f"{m.runs_failed} / {m.runs_cancelled}")
        line("median run", _minutes(m.median_seconds), "start to finish")

        self.stdout.write(self.style.MIGRATE_LABEL("\nWhat came out"))
        line("test cases", str(m.cases_total), f"{m.cases_per_run} per successful run")
        line("approved", str(m.cases_approved), f"{m.approval_rate}% of cases")
        line("rejected", str(m.cases_rejected), f"{m.rejection_rate}% - the miss rate")
        line("edited by a reviewer", str(m.cases_edited), f"{m.edit_rate}% needed rewording")
        line("criteria coverage", f"{m.coverage_average}%", "acceptance criteria traced to a case")

        self.stdout.write(self.style.MIGRATE_LABEL("\nWhat it caught"))
        line("code findings", str(m.findings_total), f"{m.findings_kept_rate}% kept, not dismissed")
        line("findings -> test case", str(m.findings_to_cases))
        line("open questions", str(m.questions_total), f"{m.questions_answered} answered")

        self.stdout.write(self.style.MIGRATE_LABEL("\nWhat it cost"))
        line("total", f"${m.cost_total:.2f}")
        line("per run", f"${m.cost_per_run:.4f}")
        line("per kept test case", f"${m.cost_per_kept_case:.4f}", "cases a reviewer did not throw out")
        line("exports", str(m.exports_total), f"{m.cases_exported} cases handed on")

        self.stdout.write(self.style.MIGRATE_LABEL("\nBy week"))
        self.stdout.write(f"  {'week':<14}{'runs':>6}{'ok':>6}{'cases':>8}{'cost':>10}")
        for period in m.weekly:
            self.stdout.write(
                f"  {period.label:<14}{period.runs:>6}{period.succeeded:>6}{period.cases:>8}{'$' + format(period.cost, '.2f'):>10}"
            )

        # The number that turns cost into savings is not ours to invent.
        self.stdout.write(
            self.style.WARNING(
                "\n  Time saved is not measured here. Multiply the kept cases by what writing one\n"
                "  by hand actually takes your team, and say which number you used.\n"
            )
        )

        if options["csv"]:
            rows = per_run_rows(since=since)
            with open(options["csv"], "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            self.stdout.write(self.style.SUCCESS(f"  Wrote {len(rows)} rows to {options['csv']}\n"))
