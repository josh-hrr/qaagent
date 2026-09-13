"""Fetch tickets from Linear.

Nothing is persisted. Tickets belong to Linear and change constantly, so the
picker reads them live rather than keeping a copy that can go stale and lie
about what a ticket says.

Every field requested here was confirmed against Linear's schema by
introspection, including the two that are easy to get wrong: ``branchName``
(Linear's suggested git branch, which the branch-matching diff-scope rule needs)
and ``Comment.resolvedAt`` (how an unresolved review comment is detected).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from connections.linear import LINEAR_API_URL, LinearError, _post  # noqa: PLC2701

from .pull_requests import PullRequestRef, deduplicate, extract_pull_requests, from_attachment

ISSUES_QUERY = """
query QaAgentIssues($teamIds: [ID!], $first: Int!) {
  issues(first: $first, filter: { team: { id: { in: $teamIds } } }, orderBy: updatedAt) {
    nodes {
      id
      identifier
      title
      description
      url
      branchName
      updatedAt
      state { name type }
      assignee { name email }
      team { id key name }
      children(first: 25) { nodes { id identifier title } }
      comments(first: 50) { nodes { id body resolvedAt } }
      attachments(first: 20) { nodes { id title subtitle url sourceType } }
    }
  }
}
"""


@dataclass(frozen=True)
class SubIssue:
    identifier: str
    title: str


@dataclass(frozen=True)
class LinearIssue:
    id: str
    identifier: str
    title: str
    description: str
    url: str
    branch_name: str
    updated_at: str
    state_name: str
    state_type: str
    assignee_name: str
    team_key: str
    team_name: str
    comment_count: int
    unresolved_comment_count: int
    sub_issues: list[SubIssue] = field(default_factory=list)
    pull_requests: list[PullRequestRef] = field(default_factory=list)

    @property
    def has_linked_pull_request(self) -> bool:
        return bool(self.pull_requests)


def _parse_issue(node: dict) -> LinearIssue:
    state = node.get("state") or {}
    assignee = node.get("assignee") or {}
    team = node.get("team") or {}

    comments = ((node.get("comments") or {}).get("nodes")) or []
    unresolved = [c for c in comments if not c.get("resolvedAt")]

    # PRs come from three places: attachments (Linear's integration), the
    # description, and comments — where teams without the integration paste
    # them. See tickets.pull_requests for why this is not a simple URL match.
    attachments = ((node.get("attachments") or {}).get("nodes")) or []
    references: list[PullRequestRef] = []
    for attachment in attachments:
        ref = from_attachment(attachment.get("url"), attachment.get("sourceType"))
        if ref:
            references.append(ref)
    references += extract_pull_requests(node.get("description"), "description")
    for comment in comments:
        references += extract_pull_requests(comment.get("body"), "comment")
    pull_requests = deduplicate(references)

    children = ((node.get("children") or {}).get("nodes")) or []

    return LinearIssue(
        id=node.get("id") or "",
        identifier=node.get("identifier") or "",
        title=node.get("title") or "",
        description=node.get("description") or "",
        url=node.get("url") or "",
        branch_name=node.get("branchName") or "",
        updated_at=node.get("updatedAt") or "",
        state_name=state.get("name") or "",
        # Linear's canonical buckets: triage, backlog, unstarted, started,
        # completed, canceled. The name is team-specific; the type is not.
        state_type=state.get("type") or "",
        assignee_name=assignee.get("name") or "",
        team_key=team.get("key") or "",
        team_name=team.get("name") or "",
        comment_count=len(comments),
        unresolved_comment_count=len(unresolved),
        sub_issues=[
            SubIssue(identifier=c.get("identifier") or "", title=c.get("title") or "")
            for c in children
        ],
        pull_requests=pull_requests,
    )


def fetch_issues(api_key: str, team_ids: list[str], limit: int = 100) -> list[LinearIssue]:
    """Issues across the given teams, most recently updated first.

    Raises :class:`connections.linear.LinearError` for anything actionable.
    """
    if not team_ids:
        return []

    data = _post(api_key, ISSUES_QUERY, {"teamIds": team_ids, "first": min(limit, 250)})
    nodes = ((data.get("issues") or {}).get("nodes")) or []
    return [_parse_issue(node) for node in nodes]


__all__ = [
    "LINEAR_API_URL",
    "LinearError",
    "LinearIssue",
    "PullRequestRef",
    "SubIssue",
    "fetch_issues",
]
