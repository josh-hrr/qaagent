"""Copy the database somewhere it will survive this machine — or this plan.

    python manage.py backup_db                                  # SQLite snapshot
    python manage.py backup_db --to "D:/OneDrive/qa-agent-backups"
    python manage.py backup_db --json                           # any database

On SQLite this uses the backup API, so it is safe to run while the server and
the worker are using the file — unlike copying it by hand.

On Postgres it writes a JSON dump instead, because that needs no ``pg_dump``
binary on the machine running it. Render's **free** Postgres has no backups of
its own and expires 30 days after creation, so on the free plan this command is
the only copy of your history that exists.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

# Reference data Django rebuilds on migrate, and sessions nobody wants back.
EXCLUDED = ["contenttypes", "auth.permission", "sessions", "admin.logentry"]


class Command(BaseCommand):
    help = "Write a timestamped copy of the database, and prune old copies."

    def add_arguments(self, parser):
        parser.add_argument("--to", help="Directory for the copy. Defaults to backend/backups/.")
        parser.add_argument("--keep", type=int, default=30, help="How many copies to keep.")
        parser.add_argument(
            "--json",
            action="store_true",
            help="Write a JSON dump rather than a file copy. Required on Postgres.",
        )

    def handle(self, *args, **options):
        database = settings.DATABASES["default"]
        is_sqlite = "sqlite" in database["ENGINE"]
        as_json = options["json"] or not is_sqlite

        target_dir = Path(options["to"]) if options["to"] else Path(settings.BASE_DIR) / "backups"
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = timezone.localtime().strftime("%Y-%m-%d_%H%M")

        if as_json:
            target = target_dir / f"qa-agent_{stamp}.json"
            with target.open("w", encoding="utf-8") as handle:
                call_command(
                    "dumpdata",
                    *[f"--exclude={label}" for label in EXCLUDED],
                    natural_foreign=True,
                    indent=2,
                    stdout=handle,
                )
            pattern = "qa-agent_*.json"
        else:
            source = Path(database["NAME"])
            if not source.exists():
                raise CommandError(f"No database at {source}.")
            target = target_dir / f"qa-agent_{stamp}.sqlite3"
            # The backup API takes a consistent snapshot of a live database; a
            # plain file copy can catch it mid-write and produce something
            # unopenable.
            with sqlite3.connect(source) as origin, sqlite3.connect(target) as copy:
                origin.backup(copy)
            pattern = "qa-agent_*.sqlite3"

        size = target.stat().st_size / 1_048_576
        self.stdout.write(self.style.SUCCESS(f"Wrote {target} ({size:.1f} MB)"))

        copies = sorted(target_dir.glob(pattern))
        for stale in copies[: max(0, len(copies) - options["keep"])]:
            stale.unlink()
            self.stdout.write(f"Removed {stale.name}")

        if as_json:
            self.stdout.write(
                "\nRestore with: python manage.py loaddata " + target.name + "\n"
                "This is a JSON dump, not a byte copy - it carries rows, not database internals.\n"
            )
        self.stdout.write(
            "\nPoint --to at a synced folder (OneDrive, Drive, Dropbox) and this survives the machine.\n"
            "The copy holds Linear ticket titles and encrypted credentials - treat it as company data.\n"
        )
