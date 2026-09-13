import base64
from unittest.mock import patch

import httpx
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User

from .apps import check_credential_encryption_key
from .crypto import DEV_KEY, CredentialDecryptionError, decrypt, encrypt, hint_for
from .linear import LinearAccount, LinearError, LinearTeamInfo, fetch_account
from .models import Connection, LinearTeam, Provider

# The test runner sets DEBUG=False, which correctly disables the development
# fallback key, so tests bring their own.
TEST_ENCRYPTION_KEY = "zqLxwEdiY2j8ta4ERsIrf2UPQgDSmRnRm6ZvCk5p_74="

API_KEY = "lin_api_TESTKEY0123456789abcdef"

ACCOUNT = LinearAccount(
    user_id="usr_1",
    name="Josué Ramírez",
    email="josue@yourcompany.com",
    organization_id="org_1",
    organization_name="Your Company",
    organization_url_key="yourcompany",
    teams=[
        LinearTeamInfo(id="team_eng", key="ENG", name="Platform"),
        LinearTeamInfo(id="team_web", key="WEB", name="Web"),
        LinearTeamInfo(id="team_mob", key="MOB", name="Mobile"),
    ],
)


@override_settings(CREDENTIAL_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class CryptoTests(TestCase):
    def test_round_trip(self):
        self.assertEqual(decrypt(encrypt(API_KEY)), API_KEY)

    def test_ciphertext_does_not_contain_the_secret(self):
        self.assertNotIn(API_KEY, encrypt(API_KEY))

    def test_encryption_is_not_deterministic(self):
        # Fernet includes a random IV, so identical keys do not produce
        # identical rows an attacker could correlate.
        self.assertNotEqual(encrypt(API_KEY), encrypt(API_KEY))

    def test_refuses_empty_values(self):
        with self.assertRaises(ValueError):
            encrypt("")

    def test_garbage_raises_a_clear_error(self):
        with self.assertRaises(CredentialDecryptionError):
            decrypt("not-a-fernet-token")

    def test_hint_reveals_only_the_tail(self):
        hint = hint_for(API_KEY)
        self.assertTrue(hint.endswith(API_KEY[-4:]))
        self.assertNotIn(API_KEY[8:-4], hint)


@override_settings(DEBUG=True, CREDENTIAL_ENCRYPTION_KEY="")
class CryptoDevFallbackTests(TestCase):
    """Exercise the development fallback key.

    The test runner forces DEBUG=False, so nothing else here ever reaches this
    branch — which is how a DEV_KEY that decoded to 35 bytes instead of 32
    shipped and broke the first real 'Connect Linear' with a 500.
    """

    def test_dev_key_is_a_valid_fernet_key(self):
        self.assertEqual(len(base64.urlsafe_b64decode(DEV_KEY)), 32)

    def test_encryption_works_with_no_key_configured(self):
        self.assertEqual(decrypt(encrypt(API_KEY)), API_KEY)

    @override_settings(DEBUG=False)
    def test_production_refuses_to_run_without_a_key(self):
        with self.assertRaises(ImproperlyConfigured):
            encrypt(API_KEY)


class EncryptionKeyCheckTests(TestCase):
    """The startup check that turns a bad key into a boot error, not a 500
    on someone's first 'Connect Linear'."""

    def ids_for(self, **overrides) -> list[str]:
        with override_settings(**overrides):
            return [m.id for m in check_credential_encryption_key(None)]

    def test_valid_key_passes(self):
        self.assertEqual(self.ids_for(CREDENTIAL_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY, DEBUG=False), [])

    def test_missing_key_warns_in_development(self):
        self.assertEqual(self.ids_for(CREDENTIAL_ENCRYPTION_KEY="", DEBUG=True), ["connections.W001"])

    def test_missing_key_is_an_error_in_production(self):
        self.assertEqual(self.ids_for(CREDENTIAL_ENCRYPTION_KEY="", DEBUG=False), ["connections.E001"])

    def test_malformed_key_is_an_error(self):
        # The 35-byte key that shipped and broke the first real connect.
        self.assertEqual(
            self.ids_for(
                CREDENTIAL_ENCRYPTION_KEY="ZGV2LW9ubHktaW5zZWN1cmUta2V5LWZvci1sb2NhbC11c2U=",
                DEBUG=True,
            ),
            ["connections.E002"],
        )

    def test_truncated_key_missing_its_padding_is_an_error(self):
        self.assertEqual(
            self.ids_for(CREDENTIAL_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY.rstrip("="), DEBUG=True),
            ["connections.E002"],
        )

    def test_dev_fallback_key_is_an_error_in_production(self):
        self.assertEqual(
            self.ids_for(CREDENTIAL_ENCRYPTION_KEY=DEV_KEY, DEBUG=False), ["connections.E003"]
        )


class LinearClientTests(TestCase):
    def post_returning(self, *, status_code=200, json_body=None, raises=None):
        def fake_post(*args, **kwargs):
            if raises:
                raise raises
            return httpx.Response(
                status_code,
                json=json_body if json_body is not None else {},
                request=httpx.Request("POST", "https://api.linear.app/graphql"),
            )

        return patch("connections.linear.httpx.post", side_effect=fake_post)

    def test_parses_a_successful_response(self):
        body = {
            "data": {
                "viewer": {"id": "usr_1", "name": "Josué", "email": "j@x.com"},
                "organization": {"id": "org_1", "name": "Your Company", "urlKey": "yourcompany"},
                "teams": {"nodes": [{"id": "team_eng", "key": "ENG", "name": "Platform"}]},
            }
        }
        with self.post_returning(json_body=body):
            account = fetch_account(API_KEY)
        self.assertEqual(account.organization_name, "Your Company")
        self.assertEqual([t.key for t in account.teams], ["ENG"])

    def test_401_maps_to_invalid_key(self):
        with self.post_returning(status_code=401):
            with self.assertRaises(LinearError) as ctx:
                fetch_account(API_KEY)
        self.assertEqual(ctx.exception.code, "invalid_key")

    def test_429_maps_to_rate_limited(self):
        with self.post_returning(status_code=429):
            with self.assertRaises(LinearError) as ctx:
                fetch_account(API_KEY)
        self.assertEqual(ctx.exception.code, "rate_limited")

    def test_graphql_auth_error_maps_to_invalid_key(self):
        body = {"errors": [{"message": "Not authenticated"}]}
        with self.post_returning(json_body=body):
            with self.assertRaises(LinearError) as ctx:
                fetch_account(API_KEY)
        self.assertEqual(ctx.exception.code, "invalid_key")

    def test_timeout_maps_to_timeout(self):
        with self.post_returning(raises=httpx.TimeoutException("slow")):
            with self.assertRaises(LinearError) as ctx:
                fetch_account(API_KEY)
        self.assertEqual(ctx.exception.code, "timeout")

    def test_the_key_is_sent_in_the_authorization_header(self):
        captured = {}

        def fake_post(url, **kwargs):
            captured.update(kwargs.get("headers") or {})
            return httpx.Response(
                200,
                json={"data": {"viewer": {"id": "u"}, "organization": {}, "teams": {"nodes": []}}},
                request=httpx.Request("POST", url),
            )

        with patch("connections.linear.httpx.post", side_effect=fake_post):
            fetch_account(API_KEY)
        self.assertEqual(captured.get("Authorization"), API_KEY)


@override_settings(CREDENTIAL_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class ConnectionApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dev@example.com")
        self.client.force_login(self.user)

    def connect(self, team_ids=("team_eng", "team_web")):
        with patch("connections.views.fetch_account", return_value=ACCOUNT):
            return self.client.post(
                reverse("connections:linear-connect"),
                {"apiKey": API_KEY, "teamIds": list(team_ids)},
                "application/json",
            )

    # -- verify -----------------------------------------------------------

    def test_verify_lists_teams_without_storing_anything(self):
        with patch("connections.views.fetch_account", return_value=ACCOUNT):
            response = self.client.post(
                reverse("connections:linear-verify"), {"apiKey": API_KEY}, "application/json"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["teams"]), 3)
        self.assertEqual(Connection.objects.count(), 0)

    def test_verify_surfaces_a_bad_key(self):
        with patch(
            "connections.views.fetch_account",
            side_effect=LinearError("invalid_key", "Linear rejected that API key."),
        ):
            response = self.client.post(
                reverse("connections:linear-verify"), {"apiKey": API_KEY}, "application/json"
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_key")

    def test_verify_rejects_a_key_of_the_wrong_shape(self):
        response = self.client.post(
            reverse("connections:linear-verify"), {"apiKey": "github_pat_xxx"}, "application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("apiKey", response.json())

    # -- connect ----------------------------------------------------------

    def test_connect_stores_the_key_encrypted(self):
        response = self.connect()
        self.assertEqual(response.status_code, 200)

        connection = Connection.objects.get(provider=Provider.LINEAR)
        self.assertNotIn(API_KEY, connection.encrypted_credential)
        self.assertEqual(connection.credential, API_KEY)
        self.assertEqual(connection.connected_by, self.user)
        self.assertEqual(connection.organization_name, "Your Company")

    def test_connect_never_returns_the_key(self):
        body = self.connect().content.decode()
        self.assertNotIn(API_KEY, body)
        self.assertNotIn("encrypted_credential", body)
        self.assertIn("...cdef", body)  # the hint is all a client gets

    def test_connect_records_team_selection(self):
        self.connect(team_ids=["team_eng"])
        teams = {t.linear_id: t.selected for t in LinearTeam.objects.all()}
        self.assertEqual(teams, {"team_eng": True, "team_web": False, "team_mob": False})

    def test_connect_rejects_teams_the_key_cannot_see(self):
        response = self.connect(team_ids=["team_eng", "team_ghost"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "unknown_teams")
        self.assertEqual(Connection.objects.count(), 0)

    def test_connect_requires_at_least_one_team(self):
        response = self.connect(team_ids=[])
        self.assertEqual(response.status_code, 400)

    def test_reconnecting_replaces_the_key_and_drops_removed_teams(self):
        self.connect()
        shrunk = LinearAccount(**{**ACCOUNT.__dict__, "teams": [ACCOUNT.teams[0]]})
        with patch("connections.views.fetch_account", return_value=shrunk):
            self.client.post(
                reverse("connections:linear-connect"),
                {"apiKey": "lin_api_ROTATED999", "teamIds": ["team_eng"]},
                "application/json",
            )
        connection = Connection.objects.get(provider=Provider.LINEAR)
        self.assertEqual(connection.credential, "lin_api_ROTATED999")
        self.assertEqual(list(connection.linear_teams.values_list("linear_id", flat=True)), ["team_eng"])
        self.assertEqual(Connection.objects.count(), 1)

    def test_a_revoked_key_leaves_no_row_behind(self):
        with patch(
            "connections.views.fetch_account",
            side_effect=LinearError("invalid_key", "Linear rejected that API key."),
        ):
            response = self.client.post(
                reverse("connections:linear-connect"),
                {"apiKey": API_KEY, "teamIds": ["team_eng"]},
                "application/json",
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Connection.objects.count(), 0)

    # -- list / update / disconnect ---------------------------------------

    def test_list_omits_credentials(self):
        self.connect()
        response = self.client.get(reverse("connections:list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(API_KEY, response.content.decode())
        self.assertFalse(response.json()["linearOAuthConfigured"])

    def test_team_selection_can_change_without_the_key(self):
        self.connect(team_ids=["team_eng"])
        response = self.client.patch(
            reverse("connections:linear-teams"), {"teamIds": ["team_web", "team_mob"]}, "application/json"
        )
        self.assertEqual(response.status_code, 200)
        selected = set(LinearTeam.objects.filter(selected=True).values_list("linear_id", flat=True))
        self.assertEqual(selected, {"team_web", "team_mob"})

    def test_disconnect_removes_everything(self):
        self.connect()
        self.assertEqual(self.client.delete(reverse("connections:linear-disconnect")).status_code, 204)
        self.assertEqual(Connection.objects.count(), 0)
        self.assertEqual(LinearTeam.objects.count(), 0)

    def test_updating_teams_before_connecting_is_404(self):
        response = self.client.patch(
            reverse("connections:linear-teams"), {"teamIds": ["team_eng"]}, "application/json"
        )
        self.assertEqual(response.status_code, 404)


class ConnectionAuthTests(TestCase):
    """Nothing here is reachable without a session, and writes need CSRF."""

    def test_every_endpoint_requires_a_session(self):
        for name, method in [
            ("connections:list", "get"),
            ("connections:linear-verify", "post"),
            ("connections:linear-connect", "post"),
            ("connections:linear-teams", "patch"),
            ("connections:linear-disconnect", "delete"),
        ]:
            with self.subTest(endpoint=name):
                response = getattr(self.client, method)(reverse(name))
                self.assertIn(response.status_code, (401, 403))

    def test_authenticated_write_still_needs_a_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(User.objects.create_user("dev@example.com"))
        response = client.post(
            reverse("connections:linear-verify"), {"apiKey": API_KEY}, "application/json"
        )
        self.assertEqual(response.status_code, 403)
