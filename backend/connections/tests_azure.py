from unittest.mock import patch

import httpx
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User

from .azure import (
    AzureAccount,
    AzureError,
    AzureRepository,
    fetch_account,
    normalize_organization,
    normalize_project,
)
from .models import Connection, DiffScopeStrategy, Provider, Repository

TEST_ENCRYPTION_KEY = "zqLxwEdiY2j8ta4ERsIrf2UPQgDSmRnRm6ZvCk5p_74="
PAT = "azdo_pat_TESTTOKEN0123456789abcd"

ACCOUNT = AzureAccount(
    user_id="usr_1",
    display_name="Josué Ramírez",
    email="josue@yourcompany.com",
    organization="yourcompany",
    repositories=[
        AzureRepository("repo_api", "core-api", "Core Platform", "main", 155_189_248,
                        "https://dev.azure.com/x/_git/core-api", "https://x@dev.azure.com/x/_git/core-api"),
        AzureRepository("repo_web", "web-client", "Core Platform", "main", 100_663_296,
                        "https://dev.azure.com/x/_git/web-client", "https://x@dev.azure.com/x/_git/web-client"),
        AzureRepository("repo_mob", "mobile-app", "Mobile", "develop", 222_298_112,
                        "https://dev.azure.com/x/_git/mobile-app", "https://x@dev.azure.com/x/_git/mobile-app"),
    ],
)


class OrganizationNormalisationTests(TestCase):
    """The organisation lands in a URL we call server-side. Anything that could
    redirect the request — or the PAT — elsewhere must be refused."""

    def test_accepts_a_bare_name(self):
        self.assertEqual(normalize_organization("yourcompany"), "yourcompany")

    def test_accepts_a_pasted_url(self):
        for value in [
            "https://dev.azure.com/yourcompany",
            "dev.azure.com/yourcompany",
            "https://dev.azure.com/yourcompany/",
            "yourcompany.visualstudio.com",
        ]:
            with self.subTest(value=value):
                self.assertEqual(normalize_organization(value), "yourcompany")

    def test_accepts_a_url_carrying_a_project_segment(self):
        self.assertEqual(
            normalize_organization("https://dev.azure.com/yourcompany/Core%20Platform"),
            "yourcompany",
        )

    def test_rejects_request_forgery_attempts(self):
        for value in [
            "evil.com",                     # a bare host
            "evil.com/yourcompany",         # org-looking segment on someone else's host
            "../../admin",                  # path traversal
            "yourcompany/../other",         # traversal that used to be silently trimmed
            "yourcompany/other",            # stray segment — do not guess which is the org
            "yourcompany@evil.com",         # userinfo trick
            "your company",                 # space
            "-leading-hyphen",
            "",
            "a" * 100,
        ]:
            with self.subTest(value=value):
                with self.assertRaises(AzureError):
                    normalize_organization(value)

    def test_project_rejects_path_separators(self):
        for value in ["a/b", "a\\b", "../etc"]:
            with self.subTest(value=value):
                with self.assertRaises(AzureError):
                    normalize_project(value)

    def test_project_may_be_blank_or_contain_spaces(self):
        self.assertEqual(normalize_project(""), "")
        self.assertEqual(normalize_project(" Core Platform "), "Core Platform")


class AzureClientTests(TestCase):
    def responder(self, *, status_code=200, json_body=None, headers=None, raises=None):
        def fake_get(url, **kwargs):
            if raises:
                raise raises
            return httpx.Response(
                status_code,
                json=json_body if json_body is not None else {},
                headers=headers or {},
                request=httpx.Request("GET", url),
            )

        return patch("connections.azure.httpx.get", side_effect=fake_get)

    def test_a_bad_pat_answering_203_with_html_is_caught(self):
        # Azure's real behaviour: not 401, but 203 plus a sign-in page. Naive
        # code treats that as success and then fails to parse.
        def fake_get(url, **kwargs):
            return httpx.Response(
                203,
                text="<html><body>Sign In</body></html>",
                headers={"Content-Type": "text/html; charset=utf-8"},
                request=httpx.Request("GET", url),
            )

        with patch("connections.azure.httpx.get", side_effect=fake_get):
            with self.assertRaises(AzureError) as ctx:
                fetch_account("yourcompany", PAT)
        self.assertEqual(ctx.exception.code, "invalid_token")

    def test_a_bad_pat_answering_200_with_an_anonymous_identity_is_caught(self):
        # Confirmed against the live API: connectionData returns a clean 200
        # for an invalid token, with Azure's anonymous identity. Trusting the
        # status code alone stores a dead credential that fails on first run.
        def fake_get(url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "authenticatedUser": {
                        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        "providerDisplayName": "Anonymous",
                        "properties": {"Account": {"$value": "Anonymous"}},
                    }
                },
                request=httpx.Request("GET", url),
            )

        with patch("connections.azure.httpx.get", side_effect=fake_get):
            with self.assertRaises(AzureError) as ctx:
                fetch_account("yourcompany", PAT)
        self.assertEqual(ctx.exception.code, "invalid_token")

    def test_a_302_to_the_sign_in_page_is_caught(self):
        def fake_get(url, **kwargs):
            return httpx.Response(
                302,
                headers={"Content-Type": "text/html", "Location": "https://login.example/"},
                request=httpx.Request("GET", url),
            )

        with patch("connections.azure.httpx.get", side_effect=fake_get):
            with self.assertRaises(AzureError) as ctx:
                fetch_account("yourcompany", PAT)
        self.assertEqual(ctx.exception.code, "invalid_token")

    def test_endpoints_use_their_own_api_versions(self):
        # connectionData is preview-only and rejects "7.1" outright.
        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            body = (
                {"authenticatedUser": {"id": "usr_1", "providerDisplayName": "Josué"}}
                if "connectionData" in url
                else {"value": []}
            )
            return httpx.Response(200, json=body, request=httpx.Request("GET", url))

        with patch("connections.azure.httpx.get", side_effect=fake_get):
            fetch_account("yourcompany", PAT)

        connection_data = next(u for u in calls if "connectionData" in u)
        repositories = next(u for u in calls if "git/repositories" in u)
        self.assertIn("api-version=7.1-preview", connection_data)
        self.assertTrue(repositories.endswith("api-version=7.1"))

    def test_401_maps_to_invalid_token(self):
        with self.responder(status_code=401):
            with self.assertRaises(AzureError) as ctx:
                fetch_account("yourcompany", PAT)
        self.assertEqual(ctx.exception.code, "invalid_token")

    def test_404_maps_to_not_found(self):
        with self.responder(status_code=404):
            with self.assertRaises(AzureError) as ctx:
                fetch_account("yourcompany", PAT)
        self.assertEqual(ctx.exception.code, "not_found")

    def test_timeout_maps_to_timeout(self):
        with self.responder(raises=httpx.TimeoutException("slow")):
            with self.assertRaises(AzureError) as ctx:
                fetch_account("yourcompany", PAT)
        self.assertEqual(ctx.exception.code, "timeout")

    def test_parses_identity_and_repositories(self):
        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            if "connectionData" in url:
                body = {
                    "authenticatedUser": {
                        "id": "usr_1",
                        "providerDisplayName": "Josué",
                        "properties": {"Account": {"$value": "josue@yourcompany.com"}},
                    }
                }
            else:
                body = {
                    "value": [
                        {
                            "id": "repo_api",
                            "name": "core-api",
                            "project": {"name": "Core Platform"},
                            "defaultBranch": "refs/heads/main",
                            "size": 155_189_248,
                            "webUrl": "https://dev.azure.com/x/_git/core-api",
                            "remoteUrl": "https://x@dev.azure.com/x/_git/core-api",
                        }
                    ],
                    "count": 1,
                }
            return httpx.Response(200, json=body, request=httpx.Request("GET", url))

        with patch("connections.azure.httpx.get", side_effect=fake_get):
            account = fetch_account("yourcompany", PAT, "Core Platform")

        self.assertEqual(account.email, "josue@yourcompany.com")
        repo = account.repositories[0]
        # "refs/heads/main" is not what a human reads.
        self.assertEqual(repo.default_branch, "main")
        self.assertTrue(any("Core%20Platform" in url for url in calls))

    def test_redirects_are_never_followed(self):
        # Following one would replay the Authorization header — and the PAT —
        # at whatever host the response points to.
        captured = {}

        def fake_get(url, **kwargs):
            captured.update(kwargs)
            return httpx.Response(
                200,
                json={"authenticatedUser": {"id": "u"}},
                request=httpx.Request("GET", url),
            )

        with patch("connections.azure.httpx.get", side_effect=fake_get):
            try:
                fetch_account("yourcompany", PAT)
            except AzureError:
                pass
        self.assertFalse(captured.get("follow_redirects", True))

    def test_the_pat_is_sent_as_basic_auth(self):
        import base64

        captured = {}

        def fake_get(url, **kwargs):
            captured.update(kwargs.get("headers") or {})
            return httpx.Response(
                200,
                json={"authenticatedUser": {"id": "u"}, "value": []},
                request=httpx.Request("GET", url),
            )

        with patch("connections.azure.httpx.get", side_effect=fake_get):
            fetch_account("yourcompany", PAT)

        header = captured.get("Authorization", "")
        self.assertTrue(header.startswith("Basic "))
        self.assertEqual(base64.b64decode(header[6:]).decode(), f":{PAT}")


@override_settings(CREDENTIAL_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class AzureApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dev@example.com")
        self.client.force_login(self.user)

    def connect(self, repository_ids=("repo_api", "repo_web"), strategy="linked_pr"):
        with patch("connections.views.fetch_azure_account", return_value=ACCOUNT):
            return self.client.post(
                reverse("connections:azure-connect"),
                {
                    "organization": "yourcompany",
                    "project": "Core Platform",
                    "pat": PAT,
                    "repositoryIds": list(repository_ids),
                    "diffScopeStrategy": strategy,
                },
                "application/json",
            )

    def test_verify_lists_repositories_without_storing_anything(self):
        with patch("connections.views.fetch_azure_account", return_value=ACCOUNT):
            response = self.client.post(
                reverse("connections:azure-verify"),
                {"organization": "yourcompany", "pat": PAT},
                "application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["repositories"]), 3)
        self.assertEqual(Connection.objects.count(), 0)

    def test_connect_stores_the_pat_encrypted(self):
        self.assertEqual(self.connect().status_code, 200)
        connection = Connection.objects.get(provider=Provider.AZURE_DEVOPS)
        self.assertNotIn(PAT, connection.encrypted_credential)
        self.assertEqual(connection.credential, PAT)

    def test_connect_never_returns_the_pat(self):
        body = self.connect().content.decode()
        self.assertNotIn(PAT, body)
        self.assertNotIn("encrypted_credential", body)

    def test_connect_records_selection_and_strategy(self):
        self.connect(repository_ids=["repo_api"], strategy="branch_name")
        connection = Connection.objects.get(provider=Provider.AZURE_DEVOPS)
        self.assertEqual(connection.diff_scope_strategy, DiffScopeStrategy.BRANCH_NAME)
        selected = {r.external_id: r.selected for r in Repository.objects.all()}
        self.assertEqual(selected, {"repo_api": True, "repo_web": False, "repo_mob": False})

    def test_default_branch_and_project_are_stored(self):
        self.connect()
        repo = Repository.objects.get(external_id="repo_mob")
        self.assertEqual(repo.default_branch, "develop")
        self.assertEqual(repo.project_name, "Mobile")

    def test_nothing_is_indexed_at_connect_time(self):
        # Cloning belongs to the run pipeline; the UI must not claim otherwise.
        self.connect()
        self.assertFalse(any(r.is_indexed for r in Repository.objects.all()))

    def test_connect_rejects_repositories_the_token_cannot_see(self):
        response = self.connect(repository_ids=["repo_api", "repo_ghost"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "unknown_repositories")
        self.assertEqual(Connection.objects.count(), 0)

    def test_connect_rejects_an_unknown_strategy(self):
        response = self.connect(strategy="vibes")
        self.assertEqual(response.status_code, 400)

    def test_a_rejected_token_leaves_no_row_behind(self):
        with patch(
            "connections.views.fetch_azure_account",
            side_effect=AzureError("invalid_token", "Azure DevOps rejected that token."),
        ):
            response = self.client.post(
                reverse("connections:azure-connect"),
                {
                    "organization": "yourcompany",
                    "pat": PAT,
                    "repositoryIds": ["repo_api"],
                    "diffScopeStrategy": "linked_pr",
                },
                "application/json",
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Connection.objects.count(), 0)

    def test_settings_can_change_without_the_token(self):
        self.connect(repository_ids=["repo_api"], strategy="linked_pr")
        response = self.client.patch(
            reverse("connections:azure-settings"),
            {"repositoryIds": ["repo_web", "repo_mob"], "diffScopeStrategy": "manual"},
            "application/json",
        )
        self.assertEqual(response.status_code, 200)
        connection = Connection.objects.get(provider=Provider.AZURE_DEVOPS)
        self.assertEqual(connection.diff_scope_strategy, DiffScopeStrategy.MANUAL)
        selected = set(Repository.objects.filter(selected=True).values_list("external_id", flat=True))
        self.assertEqual(selected, {"repo_web", "repo_mob"})

    def test_strategy_alone_can_be_updated(self):
        self.connect()
        before = set(Repository.objects.filter(selected=True).values_list("external_id", flat=True))
        self.client.patch(
            reverse("connections:azure-settings"), {"diffScopeStrategy": "branch_name"}, "application/json"
        )
        after = set(Repository.objects.filter(selected=True).values_list("external_id", flat=True))
        self.assertEqual(before, after)

    def test_disconnect_removes_everything(self):
        self.connect()
        self.assertEqual(self.client.delete(reverse("connections:azure-disconnect")).status_code, 204)
        self.assertEqual(Connection.objects.filter(provider=Provider.AZURE_DEVOPS).count(), 0)
        self.assertEqual(Repository.objects.count(), 0)

    def test_linear_and_azure_coexist(self):
        Connection.objects.create(provider=Provider.LINEAR, encrypted_credential="x")
        self.connect()
        self.assertEqual(Connection.objects.count(), 2)

    def test_endpoints_require_a_session(self):
        self.client.logout()
        for name, method in [
            ("connections:azure-verify", "post"),
            ("connections:azure-connect", "post"),
            ("connections:azure-settings", "patch"),
            ("connections:azure-disconnect", "delete"),
        ]:
            with self.subTest(endpoint=name):
                self.assertIn(getattr(self.client, method)(reverse(name)).status_code, (401, 403))
