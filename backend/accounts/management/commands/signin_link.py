"""Print a working sign-in link without going through email.

Development convenience: reading a magic link out of the runserver console means
un-wrapping a quoted-printable URL by hand. This mints the same token and prints
just the URL, on one line, ready to paste into a browser.

    python manage.py signin_link you@yourcompany.com
"""

from urllib.parse import quote

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import MagicLinkToken
from accounts.services import email_domain_allowed


class Command(BaseCommand):
    help = "Issue a sign-in link for an email address and print it (development only)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("email", help="Address to sign in as. The account is created on first use.")
        parser.add_argument(
            "--url-only",
            action="store_true",
            help="Print nothing but the URL, for piping into a browser or clipboard.",
        )

    def handle(self, *args, **options) -> None:
        # This mints credentials. Refuse outside development so it can never
        # become a way to sign in as anyone on a real deployment.
        if not settings.DEBUG:
            raise CommandError(
                "signin_link only runs with DJANGO_DEBUG=true. On a real deployment, "
                "sign in through the normal flow."
            )

        email = options["email"].strip().lower()
        if "@" not in email:
            raise CommandError(f"'{email}' does not look like an email address.")
        if not email_domain_allowed(email):
            allowed = ", ".join(settings.ALLOWED_EMAIL_DOMAINS)
            raise CommandError(
                f"'{email}' is outside ALLOWED_EMAIL_DOMAINS ({allowed}). "
                "Clear that setting in backend/.env to allow any domain locally."
            )

        _, raw_token = MagicLinkToken.issue(email, user_agent="manage.py signin_link")
        url = f"{settings.FRONTEND_URL}/auth/magic-link?token={quote(raw_token)}"

        if options["url_only"]:
            self.stdout.write(url)
            return

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(url))
        self.stdout.write("")
        # Plain ASCII only: the Windows console is cp1252 and turns anything
        # else into question marks.
        self.stdout.write(
            f"  Signs in as {email} - single use - expires in "
            f"{settings.MAGIC_LINK_TTL_MINUTES} minutes"
        )
        self.stdout.write("")
