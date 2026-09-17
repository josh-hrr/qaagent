"""Running this thing somewhere other than a laptop."""

from __future__ import annotations

import json
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from .models import Run, RunEvent, RunStatus, Stage
from .models import TestCase as GeneratedCase


class ReapRunsTests(TestCase):
    """A killed worker leaves a row that says "running" forever."""

    def stale_run(self, minutes: int, with_event: bool = False) -> Run:
        run = Run.objects.create(
            ticket_linear_id="lin_1", ticket_identifier="TES-8", status=RunStatus.RUNNING,
            stage=Stage.GENERATE,
        )
        moment = timezone.now() - timedelta(minutes=minutes)
        Run.objects.filter(pk=run.pk).update(started_at=moment, created_at=moment)
        if with_event:
            event = RunEvent.objects.create(run=run, stage=Stage.GENERATE, message="read a file")
            RunEvent.objects.filter(pk=event.pk).update(created_at=moment)
        run.refresh_from_db()
        return run

    def test_a_quiet_run_is_failed_with_an_explanation(self):
        run = self.stale_run(minutes=45)
        call_command("reap_runs", stdout=StringIO())

        run.refresh_from_db()
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(run.error_code, "interrupted")
        self.assertIn("start it again", run.error_message)
        self.assertIsNotNone(run.finished_at)
        self.assertTrue(run.events.filter(message__contains="interrupted").exists())

    def test_a_run_that_just_said_something_is_left_alone(self):
        run = self.stale_run(minutes=120, with_event=False)
        # Started two hours ago, but reported progress a minute ago.
        RunEvent.objects.create(run=run, stage=Stage.GENERATE, message="still going")

        call_command("reap_runs", stdout=StringIO())
        run.refresh_from_db()
        self.assertEqual(run.status, RunStatus.RUNNING)

    def test_queued_runs_are_not_touched(self):
        run = Run.objects.create(ticket_linear_id="lin_2", status=RunStatus.QUEUED)
        Run.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(hours=3))
        call_command("reap_runs", stdout=StringIO())
        run.refresh_from_db()
        # A queued run is waiting for a worker that may be about to start.
        self.assertEqual(run.status, RunStatus.QUEUED)

    def test_dry_run_changes_nothing(self):
        run = self.stale_run(minutes=45)
        out = StringIO()
        call_command("reap_runs", dry_run=True, stdout=out)
        run.refresh_from_db()
        self.assertEqual(run.status, RunStatus.RUNNING)
        self.assertIn("Would fail", out.getvalue())

    def test_the_window_is_configurable(self):
        run = self.stale_run(minutes=10)
        call_command("reap_runs", stdout=StringIO())
        run.refresh_from_db()
        self.assertEqual(run.status, RunStatus.RUNNING)

        call_command("reap_runs", minutes=5, stdout=StringIO())
        run.refresh_from_db()
        self.assertEqual(run.status, RunStatus.FAILED)


class ExportHistoryTests(TestCase):
    def test_carries_the_history_but_not_the_credentials(self):
        from connections.models import Connection, Provider

        user = User.objects.create_user("dev@example.com")
        run = Run.objects.create(
            ticket_linear_id="lin_1", ticket_identifier="TES-8", status=RunStatus.SUCCEEDED, created_by=user
        )
        GeneratedCase.objects.create(run=run, number=1, title="Case one")
        with override_settings(CREDENTIAL_ENCRYPTION_KEY="zqLxwEdiY2j8ta4ERsIrf2UPQgDSmRnRm6ZvCk5p_74="):
            connection = Connection.objects.create(provider=Provider.LINEAR)
            connection.set_credential("lin_api_secret")
            connection.save()

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "history.json"
            call_command("export_history", to=str(target), stdout=StringIO())
            payload = json.loads(target.read_text(encoding="utf-8"))

        models = {row["model"] for row in payload}
        self.assertIn("runs.run", models)
        self.assertIn("runs.testcase", models)
        self.assertIn("accounts.user", models)
        # A credential encrypted with this environment's key is useless in the
        # next one, and moving secrets between environments is a bad habit.
        self.assertNotIn("connections.connection", models)
        self.assertNotIn("lin_api_secret", target.name)


class SinglePageAppTests(TestCase):
    """One origin serves the API and the app, so the cookie stays first-party."""

    def setUp(self):
        from django.conf import settings

        self.index = Path(settings.FRONTEND_DIST) / "index.html"
        if not self.index.exists():
            self.skipTest("frontend is not built; run npm run build")

    def test_app_routes_return_the_shell(self):
        for path in ["/", "/runs", "/settings", "/runs/12/review"]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("text/html", response["Content-Type"])

    def test_the_api_is_not_swallowed_by_the_catch_all(self):
        # A wrong API path must still be a 404, not the app shell — otherwise a
        # typo in a fetch looks like a parse error instead of a missing route.
        self.assertEqual(self.client.get("/api/does-not-exist/").status_code, 404)
        self.assertEqual(self.client.get(reverse("accounts:options")).status_code, 200)
