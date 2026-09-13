"""Call Azure DevOps with a PAT and print what comes back.

Like ``linear_check``: the REST calls in ``connections.azure`` were written
against Microsoft's published API but have not been exercised against a real
organisation. Run this once with your own token to confirm the shape:

    python manage.py azure_check yourcompany --pat xxx
    python manage.py azure_check yourcompany --project "Core Platform" --pat xxx

Nothing is stored. Use the app itself to actually connect.
"""

from django.core.management.base import BaseCommand, CommandError

from connections.azure import AzureError, fetch_account


class Command(BaseCommand):
    help = "Verify an Azure DevOps PAT and list the repositories it can see. Stores nothing."

    def add_arguments(self, parser) -> None:
        parser.add_argument("organization", help="Organisation name, or a dev.azure.com URL.")
        parser.add_argument("--pat", required=True, help="Personal access token.")
        parser.add_argument(
            "--project", default="", help="Optional project. Omit to list the whole organisation."
        )

    def handle(self, *args, **options) -> None:
        try:
            account = fetch_account(
                options["organization"], options["pat"].strip(), options["project"]
            )
        except AzureError as exc:
            raise CommandError(f"[{exc.code}] {exc.message}") from exc

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Token works."))
        self.stdout.write(f"  user         {account.display_name} <{account.email}>")
        self.stdout.write(f"  organization {account.organization}")
        self.stdout.write(f"  repositories {len(account.repositories)}")
        self.stdout.write("")
        for repo in account.repositories:
            size = f"{repo.size_bytes / 1_048_576:.0f} MB" if repo.size_bytes else "-"
            project = f"{repo.project_name}/" if repo.project_name else ""
            self.stdout.write(
                f"    {project}{repo.name:<28} {repo.default_branch:<16} {size:>8}"
            )
        self.stdout.write("")
