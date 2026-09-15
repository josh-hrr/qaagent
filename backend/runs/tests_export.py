"""Screen 07 — the exported file is the contract with the rest of the toolchain."""

from __future__ import annotations

import io
import zipfile

from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from . import exporting
from .models import ExportRecord, Run, RunStatus, TestCaseStatus
from .models import TestCase as GeneratedCase


def settings_for(**overrides) -> exporting.ExportSettings:
    base = dict(file_format="csv", layout="table", scope="all", columns=list(exporting.DEFAULT_COLUMNS))
    base.update(overrides)
    return exporting.ExportSettings(**base)


class ExportRenderingTests(TestCase):
    def setUp(self):
        self.run = Run.objects.create(
            ticket_linear_id="lin_1",
            ticket_identifier="TES-8",
            ticket_title="Refresh rotation",
            status=RunStatus.SUCCEEDED,
            snapshot={"criteria": [{"key": "AC-1", "text": "x"}, {"key": "AC-2", "text": "y"}]},
            pull_requests=[{"repository": "core-api", "number": 7, "head_commit": "9f2c1ab" + "0" * 33}],
        )
        self.case = GeneratedCase.objects.create(
            run=self.run,
            number=1,
            title='Replay is rejected, "hard"',
            description="Check the replay path",
            preconditions="Signed in",
            steps=["Sign in", "Replay RT-1"],
            expected_result="401 refresh_token_reused",
            priority="P1",
            test_type="negative",
            status=TestCaseStatus.READY,
            traces_to=["AC-1", "/api/auth.py:12"],
            suite="auth / session",
        )

    def csv_text(self, **overrides) -> str:
        settings = settings_for(**overrides)
        return exporting.render_csv(self.run, exporting.select_cases(self.run, settings), settings)

    def test_header_row_follows_the_chosen_columns(self):
        text = self.csv_text(columns=["title", "steps"])
        # testcase# and test_title are required and always survive.
        self.assertTrue(text.startswith("testcase#,test_title,test_steps\r\n"), text[:80])

    def test_values_with_commas_and_quotes_are_quoted(self):
        row = self.csv_text().splitlines()[1]
        self.assertIn('"Replay is rejected, ""hard"""', row)

    def test_excel_needs_a_bom_and_crlf(self):
        payload, content_type = exporting.build(self.run, [self.case], settings_for())
        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", payload)
        self.assertIn("text/csv", content_type)

    def test_steps_are_numbered_in_one_cell_by_default(self):
        self.assertIn("1. Sign in 2. Replay RT-1", self.csv_text())

    def test_steps_can_be_split_on_semicolons_instead(self):
        text = self.csv_text(options={"numbered_steps": False})
        self.assertIn("Sign in; Replay RT-1", text)

    def test_actual_result_is_blank_unless_asked_otherwise(self):
        self.assertNotIn("Not run", self.csv_text())
        self.assertIn("Not run", self.csv_text(options={"blank_actual": False}))

    def test_run_header_names_the_ticket_source_and_coverage(self):
        text = self.csv_text(options={"run_header": True})
        self.assertIn("# TES-8 — Refresh rotation", text)
        self.assertIn("core-api · PR #7 · head 9f2c1ab", text)
        self.assertIn("1 cases · 1/2 acceptance criteria covered", text)

    def test_markdown_table_escapes_pipes_and_newlines(self):
        GeneratedCase.objects.filter(pk=self.case.pk).update(
            title="a | b", expected_result="line one\nline two"
        )
        settings = settings_for(file_format="md")
        text = exporting.render_markdown_table(self.run, exporting.select_cases(self.run, settings), settings)
        self.assertIn("a \\| b", text)
        self.assertIn("line one line two", text)
        self.assertEqual(len(text.strip().splitlines()), 3)  # header, rule, one row

    def test_markdown_sections_read_as_a_document(self):
        settings = settings_for(file_format="md", layout="sections")
        text = exporting.render_markdown_sections(self.run, [self.case], settings)
        self.assertIn('## TC-001 — Replay is rejected, "hard"', text)
        self.assertIn("**Test steps**", text)
        self.assertIn("1. Sign in", text)
        self.assertIn("**expected_result:** 401 refresh_token_reused", text)
        self.assertIn("**actual_result:** _(blank)_", text)

    def test_zip_holds_both_renderings(self):
        payload, content_type = exporting.build(self.run, [self.case], settings_for(file_format="zip"))
        self.assertEqual(content_type, "application/zip")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = sorted(archive.namelist())
            self.assertEqual([n.rsplit(".", 1)[1] for n in names], ["csv", "md"])
            self.assertTrue(archive.read(names[0]).startswith(b"\xef\xbb\xbf"))

    def test_preview_says_how_much_it_is_not_showing(self):
        for number in range(2, 6):
            GeneratedCase.objects.create(run=self.run, number=number, title=f"Case {number}")
        settings = settings_for()
        text = exporting.preview(self.run, exporting.select_cases(self.run, settings), settings)
        self.assertIn("… 3 more rows", text)
        self.assertNotIn("Case 4", text)

    def test_filename_carries_the_ticket_and_the_date(self):
        name = exporting.filename(self.run, settings_for(file_format="md"))
        self.assertTrue(name.startswith("TES-8_test-cases_"))
        self.assertTrue(name.endswith(".md"))


class ExportScopeTests(TestCase):
    def setUp(self):
        self.run = Run.objects.create(ticket_linear_id="lin_1", ticket_identifier="TES-8", status=RunStatus.SUCCEEDED)
        for number, status_value in enumerate(
            [TestCaseStatus.APPROVED, TestCaseStatus.DRAFT, TestCaseStatus.REJECTED, TestCaseStatus.APPROVED], start=1
        ):
            GeneratedCase.objects.create(run=self.run, number=number, title=f"Case {number}", status=status_value)

    def numbers(self, **overrides) -> list[int]:
        return [c.number for c in exporting.select_cases(self.run, settings_for(**overrides))]

    def test_all_skips_rejected_cases(self):
        self.assertEqual(self.numbers(), [1, 2, 4])

    def test_approved_only(self):
        self.assertEqual(self.numbers(scope="approved"), [1, 4])

    def test_selected_cannot_smuggle_a_rejected_case_back_in(self):
        self.assertEqual(self.numbers(scope="selected", case_numbers=[1, 3]), [1])


class ExportApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dev@example.com")
        self.client.force_login(self.user)
        self.run = Run.objects.create(
            ticket_linear_id="lin_1", ticket_identifier="TES-8", ticket_title="T", status=RunStatus.SUCCEEDED
        )
        GeneratedCase.objects.create(
            run=self.run, number=1, title="Case one", steps=["a"], status=TestCaseStatus.APPROVED
        )
        GeneratedCase.objects.create(run=self.run, number=2, title="Case two", steps=["b"])

    def url(self, name, query=""):
        return reverse(f"runs:{name}", args=[self.run.pk]) + query

    def test_preview_reports_the_real_size_and_counts(self):
        body = self.client.get(self.url("export-preview")).json()
        self.assertEqual(body["caseCount"], 2)
        self.assertEqual(body["counts"], {"all": 2, "approved": 1, "rejectedExcluded": 0})
        self.assertEqual(body["byteSize"], len(("﻿" + body["preview"]).encode("utf-8")))
        self.assertTrue(body["filename"].endswith(".csv"))
        self.assertEqual(len(body["columns"]), len(exporting.COLUMNS))

    def test_preview_follows_the_settings(self):
        body = self.client.get(self.url("export-preview", "?fileFormat=md&layout=sections&scope=approved")).json()
        self.assertIn("## TC-001 — Case one", body["preview"])
        self.assertEqual(body["caseCount"], 1)
        self.assertTrue(body["filename"].endswith(".md"))

    def test_download_returns_a_file_and_records_it(self):
        response = self.client.get(self.url("export-download", "?fileFormat=csv&columns=id,title"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment; filename=", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))

        record = ExportRecord.objects.get()
        self.assertEqual((record.run_id, record.exported_by_id), (self.run.pk, self.user.pk))
        self.assertEqual(record.case_numbers, [1, 2])
        self.assertEqual(record.columns, ["id", "title"])
        self.assertEqual(record.byte_size, len(response.content))

    def test_download_remembers_the_settings_but_not_the_selection(self):
        self.client.get(self.url("export-download", "?fileFormat=md&layout=sections&scope=selected&caseNumbers=1"))
        self.user.refresh_from_db()
        preferences = self.user.export_preferences
        self.assertEqual(preferences["fileFormat"], "md")
        self.assertEqual(preferences["layout"], "sections")
        self.assertEqual(preferences["scope"], "all")
        self.assertIn("id", preferences["columns"])

    def test_zip_download_is_one_archive(self):
        response = self.client.get(self.url("export-download", "?fileFormat=zip"))
        self.assertEqual(response["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(len(archive.namelist()), 2)

    def test_a_download_with_nothing_in_it_is_refused(self):
        response = self.client.get(self.url("export-download", "?scope=selected&caseNumbers=99"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "nothing_to_export")
        self.assertFalse(ExportRecord.objects.exists())

    def test_an_unfinished_run_cannot_be_exported(self):
        Run.objects.filter(pk=self.run.pk).update(status=RunStatus.RUNNING)
        self.assertEqual(self.client.get(self.url("export-preview")).status_code, 409)
        self.assertEqual(self.client.get(self.url("export-download")).status_code, 409)

    def test_bad_settings_are_rejected_rather_than_guessed_at(self):
        self.assertEqual(self.client.get(self.url("export-preview", "?fileFormat=pdf")).status_code, 400)
        self.assertEqual(self.client.get(self.url("export-preview", "?columns=secrets")).status_code, 400)

    def test_export_endpoints_require_a_session(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url("export-preview")).status_code, 403)
        self.assertEqual(self.client.get(self.url("export-download")).status_code, 403)

    def test_the_review_payload_lists_recent_exports(self):
        self.client.get(self.url("export-download"))
        body = self.client.get(reverse("runs:review", args=[self.run.pk])).json()
        self.assertEqual(len(body["exports"]), 1)
        self.assertEqual(body["exports"][0]["exportedBy"], "dev@example.com")
        self.assertEqual(body["exports"][0]["caseCount"], 2)
