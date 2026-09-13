"""Minimal Azure DevOps REST client.

Only what screen 03 needs: prove a personal access token works, and list the
repositories it can see. Cloning happens later, in the run pipeline.

Four Azure-specific traps are handled here, all three of the auth ones confirmed
against the live API:

* A bad PAT does **not** return 401. Depending on the endpoint Azure answers
  ``203 Non-Authoritative Information`` or ``302`` with an HTML sign-in page,
  which looks like success to naive code and then fails to parse.
* Worse, ``connectionData`` returns a clean ``200`` for a bad PAT, with an
  *anonymous* identity. Status code alone cannot tell you the token works — the
  identity has to be checked, or an invalid token verifies happily and gets
  stored as a dead credential.
* ``connectionData`` is preview-only: it rejects ``api-version=7.1`` outright
  and needs ``7.1-preview``, while ``git/repositories`` is GA at ``7.1``. The
  versions are per endpoint, not global.
* The organisation and project names come from the user and land in the URL
  path, so they are validated before use. Without that, a value like
  ``evil.com/x`` or ``..`` turns this into a request forgery that leaks the PAT
  to somebody else's server.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

AZURE_HOST = "https://dev.azure.com"
# Per endpoint, not global — connectionData is preview-only and refuses "7.1".
GIT_API_VERSION = "7.1"
CONNECTION_DATA_API_VERSION = "7.1-preview"
REQUEST_TIMEOUT_SECONDS = 20.0

# Azure's well-known anonymous identity, returned with HTTP 200 when the token
# is bad. Seeing this means "not signed in", not "signed in as this user".
ANONYMOUS_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

# Azure organisation names: alphanumeric and hyphens, not starting or ending
# with a hyphen. Anchored, so nothing containing "/", ".." or "@" gets through.
ORGANIZATION_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$")


class AzureError(Exception):
    """An Azure DevOps call failed. ``code`` is safe to hand to the frontend."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AzureRepository:
    id: str
    name: str
    project_name: str
    default_branch: str
    size_bytes: int | None
    web_url: str
    remote_url: str


@dataclass(frozen=True)
class AzureAccount:
    user_id: str
    display_name: str
    email: str
    organization: str
    repositories: list[AzureRepository] = field(default_factory=list)


def normalize_organization(value: str) -> str:
    """Accept ``yourcompany``, ``dev.azure.com/yourcompany`` or a full URL.

    Returns the bare organisation name, or raises :class:`AzureError` if it is
    not a shape Azure could possibly accept.
    """
    text = (value or "").strip().rstrip("/")
    if not text:
        raise AzureError("invalid_organization", "Enter your Azure DevOps organisation.")

    text = re.sub(r"^https?://", "", text, flags=re.IGNORECASE)

    # Never silently discard part of what was typed: a value carrying ".." is a
    # mistake at best, so say so rather than quietly using a different org.
    if ".." in text:
        raise AzureError(
            "invalid_organization",
            "That organisation name is not valid. Use the name from "
            "dev.azure.com/<organisation>.",
        )

    host, _, rest = text.partition("/")
    host_lower = host.lower()

    if host_lower == "dev.azure.com":
        # https://dev.azure.com/<org>[/<project>…] — take the org segment only.
        text = rest.split("/")[0] if rest else ""
    elif host_lower.endswith(".visualstudio.com"):
        # Legacy style: <org>.visualstudio.com
        text = host[: -len(".visualstudio.com")]
    elif "/" in text:
        # A path on some other host, or a bare name with stray segments. Both
        # are mistakes, and guessing which segment is the org is how a request
        # ends up pointed somewhere it should not go.
        raise AzureError(
            "invalid_organization",
            "Use just the organisation name, or the full dev.azure.com URL.",
        )

    if not ORGANIZATION_RE.match(text):
        raise AzureError(
            "invalid_organization",
            "That organisation name is not valid. Use the name from "
            "dev.azure.com/<organisation>.",
        )
    return text


def normalize_project(value: str) -> str:
    """Project names allow spaces and unicode, but never a path separator."""
    text = (value or "").strip().strip("/")
    if not text:
        return ""
    if "/" in text or "\\" in text or ".." in text:
        raise AzureError("invalid_project", "That project name is not valid.")
    if len(text) > 128:
        raise AzureError("invalid_project", "That project name is too long.")
    return text


def _headers(pat: str) -> dict[str, str]:
    # Azure expects Basic auth with an empty username and the PAT as password.
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "User-Agent": "qa-agent/0.1",
    }


def _get(url: str, pat: str) -> dict:
    try:
        response = httpx.get(
            url,
            headers=_headers(pat),
            timeout=REQUEST_TIMEOUT_SECONDS,
            # Never follow a redirect: it would replay the Authorization header
            # at whatever host the response points to.
            follow_redirects=False,
        )
    except httpx.TimeoutException as exc:
        raise AzureError("timeout", "Azure DevOps did not respond in time. Try again.") from exc
    except httpx.HTTPError as exc:
        raise AzureError("unreachable", "Could not reach Azure DevOps.") from exc

    if response.status_code in (401, 403):
        raise AzureError("invalid_token", "Azure DevOps rejected that personal access token.")

    # A bad or expired PAT comes back as 203, or a 302 to the sign-in page, or
    # anything HTML — never a 401. All of them mean the same thing.
    content_type = response.headers.get("Content-Type", "")
    if (
        response.status_code == 203
        or 300 <= response.status_code < 400
        or "text/html" in content_type
    ):
        raise AzureError(
            "invalid_token",
            "Azure DevOps rejected that personal access token, or it has expired.",
        )

    if response.status_code == 404:
        raise AzureError(
            "not_found",
            "Organisation or project not found. Check the names and that the token "
            "has access to them.",
        )
    if response.status_code == 429:
        raise AzureError("rate_limited", "Azure DevOps is rate limiting us. Try again shortly.")
    if response.status_code >= 500:
        raise AzureError("azure_unavailable", "Azure DevOps returned a server error.")
    if response.status_code != 200:
        raise AzureError("http_error", f"Azure DevOps returned HTTP {response.status_code}.")

    try:
        return response.json()
    except ValueError as exc:
        raise AzureError("bad_response", "Azure DevOps returned a response we could not read.") from exc


def _identity(organization: str, pat: str) -> tuple[str, str, str]:
    url = (
        f"{AZURE_HOST}/{quote(organization)}"
        f"/_apis/connectionData?api-version={CONNECTION_DATA_API_VERSION}"
    )
    data = _get(url, pat)
    user = data.get("authenticatedUser") or {}
    account = (user.get("properties") or {}).get("Account") or {}
    email = account.get("$value") if isinstance(account, dict) else ""
    user_id = user.get("id") or ""
    display_name = user.get("providerDisplayName") or user.get("displayName") or ""

    # The 200-with-anonymous trap. Without this an invalid token verifies
    # happily and gets stored, failing only on the first real run.
    if (
        user_id.lower() == ANONYMOUS_USER_ID
        or display_name.strip().lower() == "anonymous"
        or (email or "").strip().lower() == "anonymous"
    ):
        raise AzureError(
            "invalid_token",
            "Azure DevOps did not recognise that personal access token. Check it "
            "has not expired and that it covers this organisation.",
        )

    return user_id, display_name, email or ""


def _repositories(organization: str, project: str, pat: str) -> list[AzureRepository]:
    scope = f"{quote(organization)}/{quote(project)}" if project else quote(organization)
    url = f"{AZURE_HOST}/{scope}/_apis/git/repositories?api-version={GIT_API_VERSION}"
    data = _get(url, pat)

    repositories = []
    for item in data.get("value") or []:
        if not item.get("id"):
            continue
        branch = item.get("defaultBranch") or ""
        repositories.append(
            AzureRepository(
                id=item["id"],
                name=item.get("name") or "",
                project_name=((item.get("project") or {}).get("name")) or "",
                # Azure returns "refs/heads/main"; the short name is what humans read.
                default_branch=branch.removeprefix("refs/heads/"),
                size_bytes=item.get("size") if isinstance(item.get("size"), int) else None,
                web_url=item.get("webUrl") or "",
                remote_url=item.get("remoteUrl") or "",
            )
        )
    return repositories


def fetch_account(organization: str, pat: str, project: str = "") -> AzureAccount:
    """Verify a PAT and list the repositories it can see.

    ``project`` is optional — empty means every project in the organisation.
    Raises :class:`AzureError` for anything the user needs to act on.
    """
    organization = normalize_organization(organization)
    project = normalize_project(project)
    pat = (pat or "").strip()
    if not pat:
        raise AzureError("invalid_token", "Enter a personal access token.")

    user_id, display_name, email = _identity(organization, pat)
    repositories = _repositories(organization, project, pat)

    return AzureAccount(
        user_id=user_id,
        display_name=display_name,
        email=email,
        organization=organization,
        repositories=repositories,
    )
