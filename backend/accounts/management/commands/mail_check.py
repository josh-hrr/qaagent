"""Prove the mail settings work, and say plainly what broke if they don't.

    python manage.py mail_check you@yourcompany.com

Sign-in is email, so "no email arrived" is indistinguishable from "the whole
app is down" to whoever is trying to get in. This connects, sends, and reports
the actual exception instead of leaving a spinner on a screen.
"""

from __future__ import annotations

import smtplib
import socket

from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a test email and report exactly what happens."

    def add_arguments(self, parser):
        parser.add_argument("address", help="Where to send the test message.")

    def handle(self, *args, **options):
        address = options["address"]
        backend = settings.EMAIL_BACKEND

        self.stdout.write(self.style.MIGRATE_HEADING("\nMail settings in force"))
        self.stdout.write(f"  backend   {backend}")
        if "smtp" in backend:
            self.stdout.write(f"  host      {settings.EMAIL_HOST}:{settings.EMAIL_PORT}")
            self.stdout.write(f"  user      {settings.EMAIL_HOST_USER or '(none)'}")
            self.stdout.write(f"  password  {'set' if settings.EMAIL_HOST_PASSWORD else 'MISSING'}")
            self.stdout.write(f"  tls/ssl   {settings.EMAIL_USE_TLS} / {settings.EMAIL_USE_SSL}")
            self.stdout.write(f"  timeout   {getattr(settings, 'EMAIL_TIMEOUT', None)}")
        self.stdout.write(f"  from      {settings.DEFAULT_FROM_EMAIL}")

        if "console" in backend:
            self.stdout.write(
                self.style.WARNING(
                    "\n  EMAIL_URL is not set, so mail is printed here instead of sent.\n"
                    "  Nobody can sign in except by reading these logs.\n"
                )
            )

        self.stdout.write(self.style.MIGRATE_HEADING("\nConnecting"))
        try:
            connection = get_connection()
            connection.open()
            self.stdout.write(self.style.SUCCESS("  connection opened"))
            connection.close()
        except (smtplib.SMTPException, socket.timeout, OSError) as exc:
            # The three that actually happen: wrong credentials, a blocked
            # port, and a host that does not resolve.
            raise CommandError(
                f"Could not open a connection: {type(exc).__name__}: {exc}\n\n"
                "  authentication failed  -> the API key in EMAIL_URL is wrong\n"
                "  timed out              -> the port is blocked, or the host is wrong\n"
                "  name resolution        -> check the host spelling in EMAIL_URL"
            ) from exc

        self.stdout.write(self.style.MIGRATE_HEADING("\nSending"))
        try:
            sent = send_mail(
                subject="QA Agent mail check",
                message="If you are reading this, sign-in links will arrive too.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[address],
                fail_silently=False,
            )
        except (smtplib.SMTPException, socket.timeout, OSError) as exc:
            raise CommandError(
                f"Connected, but the send was refused: {type(exc).__name__}: {exc}\n\n"
                "  Most often the sender address is not verified with the provider.\n"
                f"  DEFAULT_FROM_EMAIL is currently {settings.DEFAULT_FROM_EMAIL}"
            ) from exc

        if sent:
            self.stdout.write(self.style.SUCCESS(f"  accepted for delivery to {address}"))
            self.stdout.write(
                "\n  Accepted is not the same as delivered — check the inbox, then spam.\n"
                "  A provider dashboard will show a bounce that this command cannot see.\n"
            )
        else:
            raise CommandError("The backend reported that nothing was sent.")
