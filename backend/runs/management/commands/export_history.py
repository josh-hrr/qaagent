"""Export the run history so it can be loaded somewhere else.

    python manage.py export_history --to history.json

Carries runs, their events, files read, test cases, findings, questions and
exports, plus the users those rows point at. Deliberately NOT included:

* connections — a stored credential is encrypted with this environment's key
  and would be unreadable elsewhere. Reconnect Linear and Azure in the new
  place; it takes a minute and avoids moving secrets between environments.
* sessions — signing in again is the point.

Load it on the other side with ``python manage.py loaddata history.json``.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand

# Order matters on load: users exist before the runs that reference them.
MODELS = [
    "accounts.User",
    "runs.Run",
    "runs.RunEvent",
    "runs.FileRead",
    "runs.TestCase",
    "runs.Finding",
    "runs.Ambiguity",
    "runs.ExportRecord",
]


class Command(BaseCommand):
    help = "Write runs and everything they produced to a JSON file."

    def add_arguments(self, parser):
        parser.add_argument("--to", default="history.json", help="Where to write the file.")

    def handle(self, *args, **options):
        target = Path(options["to"])
        with target.open("w", encoding="utf-8") as handle:
            call_command("dumpdata", *MODELS, indent=2, stdout=handle)

        size = target.stat().st_size / 1024
        self.stdout.write(self.style.SUCCESS(f"Wrote {target} ({size:.0f} KB)"))
        self.stdout.write(
            "\nOn the other side:\n"
            "  python manage.py migrate\n"
            f"  python manage.py loaddata {target.name}\n"
            "\nConnections are not in this file — reconnect Linear and Azure there.\n"
            "Credentials are encrypted per environment and would not decrypt anyway.\n"
        )
