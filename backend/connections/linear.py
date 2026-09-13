"""Minimal Linear GraphQL client.

Only what screen 02 needs: prove a key works, and find out which teams it can
see. Kept deliberately small and free of Django imports so it is easy to test
and easy to swap when OAuth arrives.

The queries request only fields this code actually reads. Ticket-level fields
(descriptions, sub-issues, comments) land in screen 04, against a schema we can
verify with a real key by then.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

LINEAR_API_URL = "https://api.linear.app/graphql"
REQUEST_TIMEOUT_SECONDS = 15.0

# Identity plus the teams the key can see. `viewer` is whoever owns the key.
CONNECTION_QUERY = """
query QaAgentConnectionCheck {
  viewer { id name email }
  organization { id name urlKey }
  teams(first: 100) {
    nodes { id key name }
  }
}
"""


class LinearError(Exception):
    """A Linear call failed. ``code`` is safe to hand to the frontend."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LinearTeamInfo:
    id: str
    key: str
    name: str


@dataclass(frozen=True)
class LinearAccount:
    user_id: str
    name: str
    email: str
    organization_id: str
    organization_name: str
    organization_url_key: str
    teams: list[LinearTeamInfo] = field(default_factory=list)


def _headers(api_key: str) -> dict[str, str]:
    # Linear takes a personal API key raw in Authorization; OAuth access tokens
    # use the Bearer scheme. Only personal keys are supported so far.
    return {
        "Authorization": api_key,
        "Content-Type": "application/json",
        "User-Agent": "qa-agent/0.1",
    }


def _post(api_key: str, query: str, variables: dict | None = None) -> dict:
    try:
        response = httpx.post(
            LINEAR_API_URL,
            json={"query": query, "variables": variables or {}},
            headers=_headers(api_key),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise LinearError("timeout", "Linear did not respond in time. Try again.") from exc
    except httpx.HTTPError as exc:
        raise LinearError("unreachable", "Could not reach Linear. Check your network.") from exc

    if response.status_code in (401, 403):
        raise LinearError("invalid_key", "Linear rejected that API key.")
    if response.status_code == 429:
        raise LinearError("rate_limited", "Linear is rate limiting us. Try again shortly.")
    if response.status_code >= 500:
        raise LinearError("linear_unavailable", "Linear returned a server error. Try again shortly.")
    if response.status_code != 200:
        raise LinearError("http_error", f"Linear returned HTTP {response.status_code}.")

    try:
        payload = response.json()
    except ValueError as exc:
        raise LinearError("bad_response", "Linear returned a response we could not read.") from exc

    if payload.get("errors"):
        first = payload["errors"][0]
        message = first.get("message", "Linear rejected the request.")
        # An expired or revoked key surfaces as a GraphQL error, not a 401.
        code = "invalid_key" if "authentic" in message.lower() else "linear_error"
        raise LinearError(code, message)

    data = payload.get("data")
    if not isinstance(data, dict):
        raise LinearError("bad_response", "Linear returned no data.")
    return data


def fetch_account(api_key: str) -> LinearAccount:
    """Verify a key and return who it belongs to, plus its visible teams.

    Raises :class:`LinearError` for anything the user needs to act on.
    """
    data = _post(api_key, CONNECTION_QUERY)

    viewer = data.get("viewer") or {}
    organization = data.get("organization") or {}
    team_nodes = ((data.get("teams") or {}).get("nodes")) or []

    if not viewer.get("id"):
        raise LinearError("bad_response", "Linear did not identify the key owner.")

    return LinearAccount(
        user_id=viewer["id"],
        name=viewer.get("name") or "",
        email=viewer.get("email") or "",
        organization_id=organization.get("id") or "",
        organization_name=organization.get("name") or "",
        organization_url_key=organization.get("urlKey") or "",
        teams=[
            LinearTeamInfo(id=t["id"], key=t.get("key") or "", name=t.get("name") or "")
            for t in team_nodes
            if t.get("id")
        ],
    )
