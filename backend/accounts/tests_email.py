"""Mail over HTTPS, because the host blocks SMTP."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock, patch

import httpx
from django.core import mail
from django.core.mail import EmailMultiAlternatives, send_mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

BACKEND = "accounts.email_backends.ResendAPIBackend"


def response(status: int = 200, body: str = '{"id":"abc"}') -> MagicMock:
    fake = MagicMock()
    fake.status_code = status
    fake.text = body
    return fake


@override_settings(
    EMAIL_BACKEND=BACKEND,
    RESEND_API_KEY="re_test_key",
    DEFAULT_FROM_EMAIL="QA Agent <onboarding@resend.dev>",
)
class ResendBackendTests(TestCase):
    def test_a_message_becomes_one_api_call(self):
        with patch("httpx.Client.post", return_value=response()) as post:
            sent = send_mail("Subject here", "Body here", None, ["dev@example.com"])

        self.assertEqual(sent, 1)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["from"], "QA Agent <onboarding@resend.dev>")
        self.assertEqual(payload["to"], ["dev@example.com"])
        self.assertEqual(payload["subject"], "Subject here")
        self.assertEqual(payload["text"], "Body here")
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer re_test_key")

    def test_an_html_alternative_is_carried(self):
        message = EmailMultiAlternatives("S", "plain", None, ["dev@example.com"])
        message.attach_alternative("<p>rich</p>", "text/html")
        with patch("httpx.Client.post", return_value=response()) as post:
            message.send()
        self.assertEqual(post.call_args.kwargs["json"]["html"], "<p>rich</p>")

    def test_a_refusal_is_raised_not_swallowed(self):
        refusal = response(422, '{"message":"The onboarding address only delivers to your own account"}')
        with patch("httpx.Client.post", return_value=refusal):
            with self.assertRaises(RuntimeError) as caught:
                send_mail("S", "B", None, ["stranger@example.com"])
        # The provider's reason has to reach the log, or debugging is guesswork.
        self.assertIn("only delivers", str(caught.exception))

    def test_fail_silently_means_silently(self):
        with patch("httpx.Client.post", return_value=response(500, "boom")):
            sent = send_mail("S", "B", None, ["dev@example.com"], fail_silently=True)
        self.assertEqual(sent, 0)

    def test_a_network_error_is_reported(self):
        with patch("httpx.Client.post", side_effect=httpx.ConnectError("no route")):
            with self.assertRaises(httpx.HTTPError):
                send_mail("S", "B", None, ["dev@example.com"])

    @override_settings(RESEND_API_KEY="")
    def test_no_key_is_an_error_rather_than_a_silent_no_op(self):
        with self.assertRaises(ValueError):
            send_mail("S", "B", None, ["dev@example.com"])

    def test_the_sign_in_flow_uses_it(self):
        with patch("httpx.Client.post", return_value=response()) as post:
            call_command("mail_check", "dev@example.com", stdout=StringIO())
        self.assertEqual(post.call_count, 1)

    def test_mail_check_reports_a_refusal_clearly(self):
        with patch("httpx.Client.post", return_value=response(403, '{"message":"API key is invalid"}')):
            with self.assertRaises(CommandError) as caught:
                call_command("mail_check", "dev@example.com", stdout=StringIO())
        self.assertIn("API key is invalid", str(caught.exception))


class ConsoleBackendStillWorksTests(TestCase):
    """Local development keeps printing links to the terminal."""

    def test_no_key_means_the_configured_backend_is_untouched(self):
        send_mail("S", "B", "from@example.com", ["dev@example.com"])
        self.assertEqual(len(mail.outbox), 1)
