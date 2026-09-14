"""Read code from Azure DevOps over its REST API — no clone.

Every call here was checked against a live organisation first. What that
turned up, and what the code relies on:

* A merged PR has status ``completed``; ``abandoned`` is a separate status.
  Only abandoned PRs are dropped.
* An iteration carries ``sourceRefCommit`` (the PR head) and
  ``commonRefCommit`` (the merge base). Diffing a file between those two is the
  change the PR introduces, independent of what landed on the target since.
* Change entries do **not** say whether a path is a file or a folder. The item
  fetch does (``gitObjectType``), so that is where folders are filtered out.

Read-only by construction: only GET is issued, and every request is pinned to
one repository and one commit. The agent can ask for files, but only through
:meth:`CodeReader.read_file`, which validates the path first.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from urllib.parse import quote


from connections.azure import AZURE_HOST, AzureError, _get  # noqa: PLC2701

API_VERSION = "7.1"
# Past this a file is almost certainly generated, vendored or data, and would
# burn the model budget without telling a tester anything.
MAX_FILE_CHARS = 120_000


@dataclass(frozen=True)
class PullRequestInfo:
    number: int
    title: str
    status: str  # active | completed | abandoned
    source_ref: str
    target_ref: str
    head_commit: str
    base_commit: str
    iteration_id: int


@dataclass
class ChangedFile:
    path: str
    change_type: str  # add | edit | delete | rename | ...
    head_content: str | None = None
    base_content: str | None = None
    skipped_reason: str = ""


@dataclass
class PullRequestChanges:
    info: PullRequestInfo
    files: list[ChangedFile] = field(default_factory=list)


def normalize_repo_path(path: str) -> str:
    """Canonicalise a repository path and refuse anything that escapes the repo.

    The agent chooses these paths, and its input includes ticket text and code
    written by other people — both can contain instructions aimed at it. A
    path is data, never a URL, a traversal or an absolute filesystem path.
    """
    raw = (path or "").strip().replace("\\", "/")
    if not raw or len(raw) > 1000:
        raise AzureError("invalid_path", "Path is empty or too long.")
    if "://" in raw or raw.startswith("//"):
        raise AzureError("invalid_path", "Paths must be repository paths, not URLs.")
    if any(part == ".." for part in raw.split("/")):
        raise AzureError("invalid_path", "Paths may not contain '..'.")
    if any(ord(ch) < 32 for ch in raw):
        raise AzureError("invalid_path", "Path contains control characters.")
    normalized = posixpath.normpath("/" + raw.lstrip("/"))
    return normalized


class CodeReader:
    """Read-only access to one repository, pinned to one commit."""

    def __init__(self, organization: str, project: str, repository: str, pat: str):
        self.organization = organization
        self.project = project
        self.repository = repository
        self._pat = pat
        self._base = (
            f"{AZURE_HOST}/{quote(organization)}/{quote(project)}"
            f"/_apis/git/repositories/{quote(repository)}"
        )

    # -- pull requests -------------------------------------------------

    def pull_request(self, number: int) -> PullRequestInfo:
        data = _get(f"{self._base}/pullrequests/{int(number)}?api-version={API_VERSION}", self._pat)
        iterations = _get(
            f"{self._base}/pullrequests/{int(number)}/iterations?api-version={API_VERSION}", self._pat
        ).get("value") or []
        if not iterations:
            raise AzureError("no_iterations", f"PR #{number} has no iterations to read.")
        last = iterations[-1]
        head = (last.get("sourceRefCommit") or {}).get("commitId") or ""
        base = (last.get("commonRefCommit") or {}).get("commitId") or ""
        if not head or not base:
            raise AzureError("bad_response", f"PR #{number} did not report its commits.")
        return PullRequestInfo(
            number=int(number),
            title=data.get("title") or "",
            status=data.get("status") or "",
            source_ref=data.get("sourceRefName") or "",
            target_ref=data.get("targetRefName") or "",
            head_commit=head,
            base_commit=base,
            iteration_id=int(last.get("id") or 0),
        )

    def changes(self, info: PullRequestInfo) -> PullRequestChanges:
        entries = _get(
            f"{self._base}/pullrequests/{info.number}/iterations/{info.iteration_id}/changes"
            f"?api-version={API_VERSION}&$top=2000",
            self._pat,
        ).get("changeEntries") or []

        result = PullRequestChanges(info=info)
        for entry in entries:
            item = entry.get("item") or {}
            path = item.get("path") or ""
            change_type = (entry.get("changeType") or "").lower()
            if not path:
                continue
            changed = ChangedFile(path=path, change_type=change_type)

            if "delete" not in change_type:
                changed.head_content, head_kind = self._content(path, info.head_commit)
                if head_kind == "tree":
                    continue  # a folder, not a file
                if head_kind in ("binary", "too_large"):
                    changed.skipped_reason = head_kind
            if "add" not in change_type and not changed.skipped_reason:
                changed.base_content, _ = self._content(entry.get("originalPath") or path, info.base_commit)

            result.files.append(changed)
        return result

    # -- files ----------------------------------------------------------

    def read_file(self, path: str, commit: str) -> tuple[str | None, str]:
        """Content of one file at a commit. Returns (content, kind).

        kind is ``text``, ``tree``, ``binary``, ``too_large`` or ``missing``.
        """
        return self._content(normalize_repo_path(path), commit)

    def list_directory(self, path: str, commit: str) -> list[dict]:
        folder = normalize_repo_path(path or "/")
        data = _get(
            f"{self._base}/items?scopePath={quote(folder)}&recursionLevel=OneLevel"
            f"&versionDescriptor.version={quote(commit)}&versionDescriptor.versionType=commit"
            f"&api-version={API_VERSION}",
            self._pat,
        )
        entries = []
        for item in data.get("value") or []:
            item_path = item.get("path") or ""
            if item_path.rstrip("/") == folder.rstrip("/"):
                continue
            entries.append({"path": item_path, "type": "folder" if item.get("isFolder") else "file"})
        return entries

    def _content(self, path: str, commit: str) -> tuple[str | None, str]:
        url = (
            f"{self._base}/items?path={quote(path)}&includeContent=true&includeContentMetadata=true"
            f"&versionDescriptor.version={quote(commit)}&versionDescriptor.versionType=commit"
            f"&api-version={API_VERSION}"
        )
        try:
            data = _get(url, self._pat)
        except AzureError as exc:
            if exc.code == "not_found":
                return None, "missing"
            raise

        if data.get("gitObjectType") == "tree" or data.get("isFolder"):
            return None, "tree"
        metadata = data.get("contentMetadata") or {}
        if metadata.get("isBinary"):
            return None, "binary"
        content = data.get("content")
        if content is None:
            return None, "missing"
        if len(content) > MAX_FILE_CHARS:
            return None, "too_large"
        return content, "text"


def reader_for(connection, pull_request_ref) -> CodeReader:
    """A reader for the repository a PR reference points at."""
    return CodeReader(
        organization=pull_request_ref.organization,
        project=pull_request_ref.project,
        repository=pull_request_ref.repository,
        pat=connection.credential,
    )


__all__ = [
    "MAX_FILE_CHARS",
    "AzureError",
    "ChangedFile",
    "CodeReader",
    "PullRequestChanges",
    "PullRequestInfo",
    "normalize_repo_path",
    "reader_for",
]

