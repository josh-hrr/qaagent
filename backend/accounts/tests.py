import time
from io import StringIO

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .middleware import SESSION_STARTED_KEY
from .models import MagicLinkToken, User
from .services import SignInError, consume_magic_link


def link_token_from_last_email() -> str:
    body = mail.outbox[-1].body
    return body.split("token=")[1].split()[0]


class SignInOptionsTests(TestCase):
    def test_reports_providers_and_sets_csrf_cookie(self):
        response = self.client.get(reverse("accounts:options"))
        self.assertEqual(response.status_code, 200)
        keys = {p["key"] for p in response.json()["providers"]}
        self.assertEqual(keys, {"microsoft", "google"})
        self.assertIn("qaagent_csrftoken", response.cookies)

    @override_settings(
        SSO_PROVIDERS={"google": {"label": "Google Workspace", "client_id": "", "client_secret": ""}}
    )
    def test_provider_without_credentials_is_not_configured(self):
        response = self.client.get(reverse("accounts:options"))
        self.assertFalse(response.json()["providers"][0]["configured"])


class MagicLinkRequestTests(TestCase):
    url = reverse("accounts:magic-link")

    def test_sends_a_link(self):
        response = self.client.post(self.url, {"email": "Dev@Example.com"}, "application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(MagicLinkToken.objects.count(), 1)
        # Stored hashed, never in the clear.
        self.assertNotIn(MagicLinkToken.objects.get().token_hash, mail.outbox[0].body)

    def test_answers_identically_for_unknown_addresses(self):
        User.objects.create_user("known@example.com")
        known = self.client.post(self.url, {"email": "known@example.com"}, "application/json")
        unknown = self.client.post(self.url, {"email": "nobody@example.com"}, "application/json")
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.json(), unknown.json())

    def test_requesting_again_invalidates_the_previous_link(self):
        self.client.post(self.url, {"email": "dev@example.com"}, "application/json")
        first = link_token_from_last_email()
        self.client.post(self.url, {"email": "dev@example.com"}, "application/json")

        with self.assertRaises(SignInError) as ctx:
            consume_magic_link(first)
        self.assertEqual(ctx.exception.code, "already_used")

    @override_settings(ALLOWED_EMAIL_DOMAINS=["yourcompany.com"])
    def test_rejects_a_domain_outside_the_allowlist(self):
        response = self.client.post(self.url, {"email": "dev@gmail.com"}, "application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(MAGIC_LINK_MAX_PER_EMAIL_PER_HOUR=2)
    def test_rate_limits_per_address(self):
        for _ in range(2):
            self.client.post(self.url, {"email": "dev@example.com"}, "application/json")
        response = self.client.post(self.url, {"email": "dev@example.com"}, "application/json")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "rate_limited")


class MagicLinkVerifyTests(TestCase):
    verify_url = reverse("accounts:magic-link-verify")

    def request_link(self, email: str = "dev@example.com") -> str:
        self.client.post(reverse("accounts:magic-link"), {"email": email}, "application/json")
        return link_token_from_last_email()

    def test_signs_in_and_provisions_the_user(self):
        token = self.request_link()
        response = self.client.post(self.verify_url, {"token": token}, "application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["email"], "dev@example.com")
        self.assertTrue(User.objects.filter(email="dev@example.com").exists())

        session = self.client.get(reverse("accounts:session"))
        self.assertEqual(session.status_code, 200)

    def test_a_token_works_only_once(self):
        token = self.request_link()
        self.client.post(self.verify_url, {"token": token}, "application/json")
        self.client.post(reverse("accounts:sign-out"))

        replay = self.client.post(self.verify_url, {"token": token}, "application/json")
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(replay.json()["code"], "already_used")

    def test_expired_token_is_refused(self):
        from datetime import timedelta

        from django.utils import timezone

        token = self.request_link()
        MagicLinkToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

        response = self.client.post(self.verify_url, {"token": token}, "application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "expired")

    def test_unknown_token_is_refused(self):
        response = self.client.post(self.verify_url, {"token": "not-a-real-token"}, "application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid")

    def test_deactivated_account_cannot_sign_in(self):
        User.objects.create_user("dev@example.com", is_active=False)
        token = self.request_link()
        response = self.client.post(self.verify_url, {"token": token}, "application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "inactive")


class SessionTests(TestCase):
    def test_session_requires_authentication(self):
        self.assertEqual(self.client.get(reverse("accounts:session")).status_code, 403)

    def test_sign_out_clears_the_session(self):
        user = User.objects.create_user("dev@example.com")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("accounts:session")).status_code, 200)

        self.client.post(reverse("accounts:sign-out"))
        self.assertNotEqual(self.client.get(reverse("accounts:session")).status_code, 200)


class SsoStartTests(TestCase):
    def test_unconfigured_provider_reports_501(self):
        response = self.client.get(reverse("accounts:sso-start", args=["microsoft"]))
        self.assertEqual(response.status_code, 501)
        self.assertEqual(response.json()["code"], "provider_not_configured")

    def test_unknown_provider_is_404(self):
        response = self.client.get(reverse("accounts:sso-start", args=["okta"]))
        self.assertEqual(response.status_code, 404)


class CsrfTests(TestCase):
    """DRF exempts @api_view handlers from CSRF and only re-checks inside
    SessionAuthentication, which never runs without a session. These cover the
    explicit check that closes that hole on the sign-in endpoints."""

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_magic_link_request_without_a_token_is_refused(self):
        response = self.client.post(
            reverse("accounts:magic-link"), {"email": "dev@example.com"}, "application/json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    def test_verify_without_a_token_is_refused(self):
        # Login CSRF: without this a third-party page could sign a visitor into
        # an account the attacker controls.
        response = self.client.post(
            reverse("accounts:magic-link-verify"), {"token": "whatever"}, "application/json"
        )
        self.assertEqual(response.status_code, 403)

    def test_flow_succeeds_once_the_cookie_is_primed(self):
        options = self.client.get(reverse("accounts:options"))
        csrf = options.cookies["qaagent_csrftoken"].value

        sent = self.client.post(
            reverse("accounts:magic-link"),
            {"email": "dev@example.com"},
            "application/json",
            headers={"x-csrftoken": csrf},
        )
        self.assertEqual(sent.status_code, 200)

        verified = self.client.post(
            reverse("accounts:magic-link-verify"),
            {"token": link_token_from_last_email()},
            "application/json",
            headers={"x-csrftoken": csrf},
        )
        self.assertEqual(verified.status_code, 200)

    def test_reading_options_needs_no_token(self):
        self.assertEqual(self.client.get(reverse("accounts:options")).status_code, 200)


class AbsoluteSessionTimeoutTests(TestCase):
    """A sliding expiry alone never ends a session that keeps being used —
    including one an attacker keeps warm with a stolen cookie."""

    def setUp(self):
        self.user = User.objects.create_user("dev@example.com")
        self.client.force_login(self.user)
        self.url = reverse("accounts:session")

    def age_session_by(self, seconds: float) -> None:
        session = self.client.session
        session[SESSION_STARTED_KEY] = time.time() - seconds
        session.save()

    def test_session_survives_inside_the_window(self):
        self.age_session_by(settings.SESSION_ABSOLUTE_TIMEOUT - 60)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_session_ends_past_the_window(self):
        self.age_session_by(settings.SESSION_ABSOLUTE_TIMEOUT + 60)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_activity_does_not_extend_the_absolute_cap(self):
        self.age_session_by(settings.SESSION_ABSOLUTE_TIMEOUT - 5)
        self.assertEqual(self.client.get(self.url).status_code, 200)  # request #1
        self.age_session_by(settings.SESSION_ABSOLUTE_TIMEOUT + 5)
        self.assertEqual(self.client.get(self.url).status_code, 403)  # still expires

    def test_sign_in_stamps_the_start_time(self):
        self.client.logout()
        options = self.client.get(reverse("accounts:options"))
        csrf = options.cookies[settings.CSRF_COOKIE_NAME].value
        self.client.post(
            reverse("accounts:magic-link"),
            {"email": "dev@example.com"},
            "application/json",
            headers={"x-csrftoken": csrf},
        )
        self.client.post(
            reverse("accounts:magic-link-verify"),
            {"token": link_token_from_last_email()},
            "application/json",
            headers={"x-csrftoken": csrf},
        )
        self.assertIn(SESSION_STARTED_KEY, self.client.session)

    def test_a_session_without_a_stamp_gets_one(self):
        # Sessions created before this middleware existed must not live forever.
        session = self.client.session
        del session[SESSION_STARTED_KEY]
        session.save()

        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertIn(SESSION_STARTED_KEY, self.client.session)


class SignInLinkCommandTests(TestCase):
    def run_command(self, *args, **kwargs) -> str:
        out = StringIO()
        call_command("signin_link", *args, stdout=out, **kwargs)
        return out.getvalue()

    @override_settings(DEBUG=True)
    def test_prints_a_link_that_signs_in(self):
        url = self.run_command("dev@example.com", "--url-only").strip()
        token = url.split("token=")[1]

        options = self.client.get(reverse("accounts:options"))
        response = self.client.post(
            reverse("accounts:magic-link-verify"),
            {"token": token},
            "application/json",
            headers={"x-csrftoken": options.cookies["qaagent_csrftoken"].value},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["email"], "dev@example.com")

    @override_settings(DEBUG=False)
    def test_refuses_to_run_outside_development(self):
        # It mints credentials; it must never be a production back door.
        with self.assertRaises(CommandError):
            self.run_command("dev@example.com")

    @override_settings(DEBUG=True, ALLOWED_EMAIL_DOMAINS=["yourcompany.com"])
    def test_respects_the_domain_allowlist(self):
        with self.assertRaises(CommandError):
            self.run_command("dev@gmail.com")

    @override_settings(DEBUG=True)
    def test_rejects_a_non_address(self):
        with self.assertRaises(CommandError):
            self.run_command("not-an-email")


class UserModelTests(TestCase):
    def test_initials_and_display_name(self):
        user = User.objects.create_user("josue.ramirez@example.com", full_name="Josué Ramírez")
        self.assertEqual(user.initials, "JR")
        self.assertEqual(user.display_name, "Josué Ramírez")

    def test_initials_fall_back_to_the_address(self):
        user = User.objects.create_user("dana.okafor@example.com")
        self.assertEqual(user.initials, "DO")
        self.assertEqual(user.display_name, "dana.okafor")

    def test_email_is_normalised_and_password_unusable(self):
        user = User.objects.create_user("Mixed.Case@Example.COM")
        self.assertEqual(user.email, "mixed.case@example.com")
        self.assertFalse(user.has_usable_password())
