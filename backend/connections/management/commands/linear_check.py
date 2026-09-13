"""Call Linear with a key and print what comes back.

The GraphQL queries in ``connections.linear`` were written against Linear's
published schema but have not been exercised against a real workspace. Run this
once with your own key to confirm the shape before trusting the UI:

    python manage.py linear_check lin_api_xxx

Nothing is stored. Use the app itself to actually connect.
"""

from django.core.management.base import BaseCommand, CommandError

from connections.linear import LinearError, fetch_account


class Command(BaseCommand):
    help = "Verify a Linear API key and list the teams it can see. Stores nothing."

    def add_arguments(self, parser) -> None:
        parser.add_argument("api_key", help="A Linear personal API key (lin_api_...).")

    def handle(self, *args, **options) -> None:
        try:
            account = fetch_account(options["api_key"].strip())
        except LinearError as exc:
            raise CommandError(f"[{exc.code}] {exc.message}") from exc

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Key works."))
        self.stdout.write(f"  user         {account.name} <{account.email}>")
        self.stdout.write(f"  organization {account.organization_name} ({account.organization_url_key})")
        self.stdout.write(f"  teams        {len(account.teams)}")
        self.stdout.write("")
        for team in account.teams:
            self.stdout.write(f"    {team.key:<8} {team.name}")
        self.stdout.write("")
