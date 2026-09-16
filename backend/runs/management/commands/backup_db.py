"""Copy the database somewhere it will survive this laptop.

    python manage.py backup_db
    python manage.py backup_db --to "C:/Users/you/OneDrive/qa-agent-backups"

Uses SQLite's own backup API, so it is safe to run while the server and the
worker are using the database — unlike copying the file by hand.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Write a timestamped copy of the database, and prune old copies."

    def add_arguments(self, parser):
        parser.add_argument("--to", help="Directory for the copy. Defaults to backend/backups/.")
        parser.add_argument("--keep", type=int, default=30, help="How many copies to keep.")

    def handle(self, *args, **options):
        database = settings.DATABASES["default"]
        if "sqlite" not in database["ENGINE"]:
            raise CommandError(
                "This command backs up SQLite. On Postgres use pg_dump, which your host probably "
                "runs for you already."
            )

        source = Path(database["NAME"])
        if not source.exists():
            raise CommandError(f"No database at {source}.")

        target_dir = Path(options["to"]) if options["to"] else Path(settings.BASE_DIR) / "backups"
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = timezone.localtime().strftime("%Y-%m-%d_%H%M")
        target = target_dir / f"qa-agent_{stamp}.sqlite3"

        # The backup API takes a consistent snapshot of a live database; a plain
        # file copy can catch it mid-write and produce something unopenable.
        with sqlite3.connect(source) as origin, sqlite3.connect(target) as copy:
            origin.backup(copy)

        size = target.stat().st_size / 1_048_576
        self.stdout.write(self.style.SUCCESS(f"Wrote {target} ({size:.1f} MB)"))

        copies = sorted(target_dir.glob("qa-agent_*.sqlite3"))
        for stale in copies[: max(0, len(copies) - options["keep"])]:
            stale.unlink()
            self.stdout.write(f"Removed {stale.name}")

        self.stdout.write(
            "\nPoint --to at a synced folder (OneDrive, Drive, Dropbox) and this survives the machine.\n"
            "The copy holds Linear ticket titles and encrypted credentials - treat it as company data.\n"
        )
