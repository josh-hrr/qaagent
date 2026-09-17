"""Fail runs whose worker died mid-flight.

A run is marked ``running`` by the worker and finished by the same process. If
that process is killed — a deploy, a restart, a free instance spinning down —
nothing ever finishes the row, and the screen polls a run that will never move.

Run this on worker start, and on a schedule if runs matter more than the few
seconds it takes.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from ...models import Run, RunEvent, RunStatus, Stage

# Long enough that a slow model round is never mistaken for a dead worker.
DEFAULT_MINUTES = 30


class Command(BaseCommand):
    help = "Mark abandoned runs as failed so they stop looking live."

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes",
            type=int,
            default=DEFAULT_MINUTES,
            help=f"How quiet a running run must be before it counts as abandoned (default {DEFAULT_MINUTES}).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Say what would change, change nothing.")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=options["minutes"])
        stale = []
        for run in Run.objects.filter(status=RunStatus.RUNNING):
            last_event = run.events.order_by("-created_at").values_list("created_at", flat=True).first()
            # The last sign of life is the newest event, or the start itself.
            heartbeat = last_event or run.started_at or run.created_at
            if heartbeat < cutoff:
                stale.append((run, heartbeat))

        if not stale:
            self.stdout.write("No abandoned runs.")
            return

        for run, heartbeat in stale:
            age = int((timezone.now() - heartbeat).total_seconds() // 60)
            self.stdout.write(f"run {run.pk} ({run.ticket_identifier}) quiet for {age} min")
            if options["dry_run"]:
                continue
            run.status = RunStatus.FAILED
            run.error_code = "interrupted"
            run.error_message = (
                "This run stopped part-way through, most likely because the server restarted. "
                "Nothing was charged for work that did not finish — start it again."
            )
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error_code", "error_message", "finished_at"])
            RunEvent.objects.create(
                run=run,
                stage=run.stage or Stage.FETCH_TICKET,
                message="failed: the run was interrupted and did not resume",
            )

        verb = "Would fail" if options["dry_run"] else "Failed"
        self.stdout.write(self.style.SUCCESS(f"{verb} {len(stale)} abandoned run(s)."))
