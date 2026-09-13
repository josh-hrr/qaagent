"""Print a fresh CREDENTIAL_ENCRYPTION_KEY for the environment file."""

from django.core.management.base import BaseCommand

from connections.crypto import generate_key


class Command(BaseCommand):
    help = "Generate a Fernet key for CREDENTIAL_ENCRYPTION_KEY."

    def handle(self, *args, **options) -> None:
        self.stdout.write("")
        self.stdout.write(f"CREDENTIAL_ENCRYPTION_KEY={generate_key()}")
        self.stdout.write("")
        self.stdout.write(
            "  Put this in backend/.env. Keep it separate from DJANGO_SECRET_KEY:"
        )
        self.stdout.write(
            "  rotating SECRET_KEY signs everyone out, and must not also make"
        )
        self.stdout.write("  every stored third-party credential unreadable.")
        self.stdout.write("")
