"""Can this ticket produce trustworthy test cases yet?

The picker's job is to stop someone pressing Generate on a ticket that cannot
produce a useful answer — and to say exactly what is missing rather than
failing halfway through a run.

Blocking and warning are different, and the difference matters:

* ``blocked`` — the run would produce nothing worth reading. Nobody wrote the
  requirements, or there is no code to compare against.
* ``warning`` — the run will work, but a reviewer should know something was
  imperfect: a fallback was used, or the ticket moved after it was written.
"""

from __future__ import annotations

from dataclasses import dataclass

from connections.models import DiffScopeStrategy

from .criteria import Criterion
from .linear_issues import LinearIssue

OK = "ok"
WARNING = "warning"
BLOCKED = "blocked"


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    detail: str
    status: str


@dataclass(frozen=True)
class Readiness:
    status: str
    checks: list[Check]

    @property
    def is_blocked(self) -> bool:
        return self.status == BLOCKED

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.checks if c.status == WARNING)


def _criteria_check(issue: LinearIssue, criteria: list[Criterion]) -> Check:
    """Three outcomes, because most real tickets sit in the middle one.

    A formal acceptance-criteria section is the exception, not the rule. Refusing
    to run without one would make the tool useless on the tickets people
    actually write — and inferring intent from a description, then raising what
    is ambiguous, is precisely the job. Only a ticket with *nothing* written
    down is genuinely untestable.
    """
    label = "Acceptance criteria in the description"

    if criteria:
        return Check(key="criteria", label=label, detail=f"{len(criteria)} found", status=OK)

    if issue.description.strip():
        return Check(
            key="criteria",
            label=label,
            detail="none — intent inferred",
            status=WARNING,
        )

    return Check(
        key="criteria",
        label=label,
        # Nothing written down at all. The diff can only say what the code does,
        # never what it was supposed to do.
        detail="no description",
        status=BLOCKED,
    )


def _pull_request_detail(prs) -> str:
    if len(prs) == 1:
        pr = prs[0]
        return f"PR #{pr.number} · {pr.repository}" if pr.number else "linked PR"
    repositories = {p.repository.lower() for p in prs if p.repository}
    return f"{len(prs)} PRs · {len(repositories) or 1} repo{'s' if len(repositories) > 1 else ''}"


def _diff_scope_check(issue: LinearIssue, strategy: str, connected_repositories: set[str]) -> Check:
    label = "Code change located"

    if issue.has_linked_pull_request:
        # A PR with no parsed repository (an integration URL we could not read)
        # cannot be checked against the connection, so it is given the benefit
        # of the doubt rather than reported as out of scope.
        in_scope = [
            p for p in issue.pull_requests
            if not p.repository or p.repository.lower() in connected_repositories
        ]
        if in_scope:
            return Check(key="diff_scope", label=label, detail=_pull_request_detail(in_scope), status=OK)
        # Found PRs, but only in repositories nobody connected — the run would
        # have no code to read for them. Say so instead of silently ignoring them.
        return Check(
            key="diff_scope",
            label=label,
            detail=f"PR in a repo you haven't connected ({issue.pull_requests[0].repository})",
            status=WARNING,
        )

    if strategy == DiffScopeStrategy.LINKED_PR:
        # Not fatal: the run falls through to matching a branch by ticket id.
        return Check(
            key="diff_scope",
            label=label,
            detail="no linked PR — will match a branch",
            status=WARNING,
        )
    if strategy == DiffScopeStrategy.BRANCH_NAME:
        return Check(
            key="diff_scope",
            label=label,
            detail=issue.branch_name or "branch match at run time",
            status=OK if issue.branch_name else WARNING,
        )
    return Check(key="diff_scope", label=label, detail="you pick at run time", status=OK)


def _repository_check(repository_count: int) -> Check:
    label = "Repository connected"
    if repository_count > 0:
        return Check(
            key="repository",
            label=label,
            detail=f"{repository_count} selected",
            status=OK,
        )
    return Check(
        key="repository",
        label=label,
        detail="none — connect one first",
        status=BLOCKED,
    )


def _comments_check(issue: LinearIssue) -> Check:
    label = "Unresolved comments on the ticket"
    if issue.unresolved_comment_count == 0:
        return Check(key="comments", label=label, detail="none", status=OK)
    return Check(
        key="comments",
        label=label,
        # A live discussion usually means the requirements moved after the
        # description was written, so generated cases may be out of date.
        detail=f"{issue.unresolved_comment_count} open",
        status=WARNING,
    )


def _state_check(issue: LinearIssue) -> Check | None:
    if issue.state_type in ("completed", "canceled"):
        return Check(
            key="state",
            label="Ticket is still open",
            detail=issue.state_name.lower(),
            status=WARNING,
        )
    return None


def assess(
    issue: LinearIssue,
    criteria: list[Criterion],
    *,
    repository_count: int,
    strategy: str,
    connected_repositories: set[str] | None = None,
) -> Readiness:
    """``connected_repositories`` holds selected repository names, lowercased."""
    checks = [
        _criteria_check(issue, criteria),
        _diff_scope_check(issue, strategy, connected_repositories or set()),
        _repository_check(repository_count),
        # Disabled: the team does not use Linear's "resolve comment", because
        # resolving hides the comment's content — so every open discussion would
        # count as unresolved and the warning would be permanent noise.
        # _comments_check() is kept intact; uncomment to re-enable, and un-skip
        # ReadinessTests.test_unresolved_comments_warn.
        # _comments_check(issue),
    ]
    state_check = _state_check(issue)
    if state_check:
        checks.append(state_check)

    if any(c.status == BLOCKED for c in checks):
        status = BLOCKED
    elif any(c.status == WARNING for c in checks):
        status = WARNING
    else:
        status = OK

    return Readiness(status=status, checks=checks)
