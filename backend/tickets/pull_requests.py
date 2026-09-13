"""Find pull requests a ticket refers to.

Linear only records a PR as an *attachment* when its official integration is
installed. Many teams skip that and paste the link into a comment or the
description instead, so all three places are read.

Two things seen in real tickets make naive URL matching wrong:

* Linear stores comments as markdown and escapes underscores, so the same link
  can arrive as ``…/_git/…`` in one comment and ``…/\\_git/…`` in another.
  Unescape first, or one PR looks like two — or like none.
* The same PR is often pasted more than once. References are deduplicated on
  what identifies a PR (host, org, project, repo, number), not on the raw text.

A ticket referring to several *different* PRs is normal — a backend and a
frontend repo, or a follow-up fix — so every distinct one is kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote

# Where a reference was found. Lower sorts first: an attachment was put there
# deliberately by an integration, a comment may be a passing mention.
SOURCE_PRIORITY = {"attachment": 0, "description": 1, "comment": 2}

_SEGMENT = r"[^/\s)\]>\"'<]+"

AZURE_RE = re.compile(
    rf"https?://dev\.azure\.com/(?P<org>{_SEGMENT})/(?P<project>{_SEGMENT})"
    rf"/_git/(?P<repo>{_SEGMENT})/pullrequest/(?P<number>\d+)",
    re.IGNORECASE,
)
AZURE_LEGACY_RE = re.compile(
    rf"https?://(?P<org>[A-Za-z0-9-]+)\.visualstudio\.com/(?P<project>{_SEGMENT})"
    rf"/_git/(?P<repo>{_SEGMENT})/pullrequest/(?P<number>\d+)",
    re.IGNORECASE,
)
GITHUB_RE = re.compile(
    rf"https?://github\.com/(?P<org>{_SEGMENT})/(?P<repo>{_SEGMENT})/pull/(?P<number>\d+)",
    re.IGNORECASE,
)

# Markdown escapes Linear adds: \_  \*  \[  \]  \(  \)  \#  \.  \-
_MARKDOWN_ESCAPE_RE = re.compile(r"\\([_*\[\]()#.\-])")


@dataclass(frozen=True)
class PullRequestRef:
    provider: str  # "azure_devops" or "github"
    organization: str
    project: str
    repository: str
    number: int
    url: str
    source: str  # "attachment", "description" or "comment"

    @property
    def identity(self) -> tuple:
        """What makes two references the same PR, regardless of how they were written."""
        if self.number:
            return (
                self.provider,
                self.organization.lower(),
                self.project.lower(),
                self.repository.lower(),
                self.number,
            )
        return ("url", self.url.lower().rstrip("/"))


def _unescape(text: str) -> str:
    return _MARKDOWN_ESCAPE_RE.sub(r"\1", text)


def extract_pull_requests(text: str | None, source: str) -> list[PullRequestRef]:
    """Every PR link in a block of text, in order of appearance."""
    if not text:
        return []
    text = _unescape(text)

    found: list[tuple[int, PullRequestRef]] = []

    for pattern in (AZURE_RE, AZURE_LEGACY_RE):
        for match in pattern.finditer(text):
            org, project, repo = (unquote(match.group(k)) for k in ("org", "project", "repo"))
            number = int(match.group("number"))
            found.append(
                (
                    match.start(),
                    PullRequestRef(
                        provider="azure_devops",
                        organization=org,
                        project=project,
                        repository=repo,
                        number=number,
                        # Rebuilt rather than copied, so an escaped or legacy
                        # link still opens the canonical page.
                        url=f"https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{number}",
                        source=source,
                    ),
                )
            )

    for match in GITHUB_RE.finditer(text):
        org, repo = unquote(match.group("org")), unquote(match.group("repo"))
        number = int(match.group("number"))
        found.append(
            (
                match.start(),
                PullRequestRef(
                    provider="github",
                    organization=org,
                    project="",
                    repository=repo,
                    number=number,
                    url=f"https://github.com/{org}/{repo}/pull/{number}",
                    source=source,
                ),
            )
        )

    found.sort(key=lambda item: item[0])
    return [ref for _, ref in found]


def from_attachment(url: str | None, source_type: str | None) -> PullRequestRef | None:
    """An attachment Linear's integration created, if it points at a PR."""
    refs = extract_pull_requests(url, "attachment")
    if refs:
        return refs[0]
    # An integration may link a PR through a URL we cannot parse; keep it so
    # the reviewer still sees it, just without repository details.
    if url and source_type and any(k in source_type.lower() for k in ("github", "azure", "gitlab", "bitbucket")):
        return PullRequestRef(
            provider=source_type,
            organization="",
            project="",
            repository="",
            number=0,
            url=url,
            source="attachment",
        )
    return None


def deduplicate(refs: list[PullRequestRef]) -> list[PullRequestRef]:
    """One entry per distinct PR, keeping the most deliberate source for each."""
    best: dict[tuple, PullRequestRef] = {}
    order: list[tuple] = []
    for ref in refs:
        key = ref.identity
        current = best.get(key)
        if current is None:
            best[key] = ref
            order.append(key)
        elif SOURCE_PRIORITY.get(ref.source, 9) < SOURCE_PRIORITY.get(current.source, 9):
            best[key] = ref
    return [best[key] for key in order]
