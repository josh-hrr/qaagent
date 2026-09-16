"""The settings screen is read by testers, not operators."""

from __future__ import annotations

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from runs import exporting


@override_settings(
    LLM_MODEL="claude-opus-5",
    LLM_EFFORT="high",
    RUN_COST_CAP_USD=1.0,
    RUN_MAX_FILES=40,
    RUN_MAX_ROUNDS=12,
    WORKSPACE_MONTHLY_CAP_USD=50.0,
    SESSION_IDLE_TIMEOUT_HOURS=12,
    SESSION_ABSOLUTE_TIMEOUT_HOURS=168,
    MAGIC_LINK_TTL_MINUTES=15,
    ALLOWED_EMAIL_DOMAINS=["yourcompany.com"],
)
class WorkspaceSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dev@example.com")
        self.client.force_login(self.user)

    def body(self) -> dict:
        return self.client.get(reverse("workspace-settings")).json()

    def test_reports_the_running_configuration_in_words(self):
        body = self.body()
        self.assertEqual(body["generation"]["modelName"], "Claude Opus 5")
        self.assertEqual(body["generation"]["costCapUsd"], "1.00")
        self.assertEqual(body["signIn"]["idleTimeout"], "12 hours")
        self.assertEqual(body["signIn"]["absoluteTimeout"], "7 days")
        self.assertEqual(body["signIn"]["allowedEmailDomains"], ["yourcompany.com"])
        self.assertEqual(body["spend"]["capUsd"], "50.0")

    def test_says_nothing_about_how_the_server_is_configured(self):
        # No variable names, no file paths, no management commands: a reader of
        # this screen cannot act on them and should not be shown them.
        raw = self.client.get(reverse("workspace-settings")).content.decode()
        for leak in ["env", ".env", "manage.py", "DJANGO", "LLM_MODEL", "RUN_MAX", "SESSION_", "settings.py"]:
            self.assertNotIn(leak, raw, leak)

    def test_export_defaults_start_from_the_shared_defaults(self):
        defaults = self.body()["exportDefaults"]
        self.assertEqual(defaults["fileFormat"], "csv")
        self.assertEqual(defaults["columns"], list(exporting.DEFAULT_COLUMNS))
        self.assertTrue(defaults["options"]["numbered_steps"])

    def test_export_defaults_can_be_changed(self):
        response = self.client.patch(
            reverse("export-defaults"),
            {
                "fileFormat": "md",
                "layout": "sections",
                "columns": ["title", "steps"],
                "options": {"numbered_steps": False},
            },
            "application/json",
        )
        self.assertEqual(response.status_code, 200)
        defaults = response.json()["exportDefaults"]
        # The required columns survive, in canonical order.
        self.assertEqual(defaults["columns"], ["id", "title", "steps"])
        self.assertEqual(defaults["fileFormat"], "md")
        self.assertFalse(defaults["options"]["numbered_steps"])

        self.user.refresh_from_db()
        self.assertEqual(self.user.export_preferences["layout"], "sections")

    def test_rubbish_defaults_are_refused(self):
        for payload in [
            {"fileFormat": "pdf", "layout": "table", "columns": ["title"], "options": {}},
            {"fileFormat": "csv", "layout": "table", "columns": ["secrets"], "options": {}},
            {"fileFormat": "csv", "layout": "table", "columns": ["title"], "options": {"drop_table": True}},
        ]:
            with self.subTest(payload=payload):
                response = self.client.patch(reverse("export-defaults"), payload, "application/json")
                self.assertEqual(response.status_code, 400)

    def test_settings_require_a_session(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("workspace-settings")).status_code, 403)
        self.assertEqual(self.client.patch(reverse("export-defaults")).status_code, 403)
