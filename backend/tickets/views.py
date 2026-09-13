from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from connections.linear import LinearError
from connections.models import Connection, Provider

from .criteria import extract_criteria
from .linear_issues import LinearIssue, fetch_issues
from .readiness import Readiness, assess

log = logging.getLogger(__name__)

# Open work first, finished work last. Linear's state *names* are per team, so
# ordering keys off the state type, which is not.
STATE_ORDER = {
    "started": 0,
    "unstarted": 1,
    "triage": 2,
    "backlog": 3,
    "completed": 4,
    "canceled": 5,
}


def _serialize(issue: LinearIssue, criteria, readiness: Readiness, connected_repositories: set[str]) -> dict:
    return {
        "id": issue.id,
        "identifier": issue.identifier,
        "title": issue.title,
        "description": issue.description,
        "url": issue.url,
        "branchName": issue.branch_name,
        "updatedAt": issue.updated_at,
        "state": {"name": issue.state_name, "type": issue.state_type},
        "assigneeName": issue.assignee_name,
        "teamKey": issue.team_key,
        "teamName": issue.team_name,
        "criteria": [{"key": c.key, "text": c.text} for c in criteria],
        "subIssues": [{"identifier": s.identifier, "title": s.title} for s in issue.sub_issues],
        "commentCount": issue.comment_count,
        "unresolvedCommentCount": issue.unresolved_comment_count,
        "pullRequests": [
            {
                "provider": p.provider,
                "organization": p.organization,
                "project": p.project,
                "repository": p.repository,
                "number": p.number,
                "url": p.url,
                "source": p.source,
                "inConnectedRepository": not p.repository or p.repository.lower() in connected_repositories,
            }
            for p in issue.pull_requests
        ],
        "readiness": {
            "status": readiness.status,
            "warningCount": readiness.warning_count,
            "checks": [
                {"key": c.key, "label": c.label, "detail": c.detail, "status": c.status}
                for c in readiness.checks
            ],
        },
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_tickets(request: Request) -> Response:
    """Tickets from the synced Linear teams, with readiness worked out.

    Read live rather than from a local copy: a ticket's description changes, and
    generating tests from a stale one is worse than not generating them.
    """
    linear = Connection.objects.filter(provider=Provider.LINEAR).first()
    if linear is None:
        return Response(
            {
                "detail": "Linear is not connected yet.",
                "code": "linear_not_connected",
            },
            status=status.HTTP_409_CONFLICT,
        )

    team_ids = list(linear.linear_teams.filter(selected=True).values_list("linear_id", flat=True))
    if not team_ids:
        return Response(
            {
                "detail": "No Linear teams are selected.",
                "code": "no_teams_selected",
            },
            status=status.HTTP_409_CONFLICT,
        )

    source = (
        Connection.objects.filter(provider__in=[Provider.AZURE_DEVOPS, Provider.GITHUB])
        .prefetch_related("repositories")
        .first()
    )
    selected_repositories = (
        list(source.repositories.filter(selected=True).values_list("name", flat=True)) if source else []
    )
    repository_count = len(selected_repositories)
    connected_repositories = {name.lower() for name in selected_repositories}
    strategy = source.diff_scope_strategy if source else ""

    try:
        issues = fetch_issues(linear.credential, team_ids, limit=100)
    except LinearError as exc:
        # A revoked key shows up here first, so record it on the connection —
        # the connections screen can then explain itself without a second call.
        if exc.code == "invalid_key":
            linear.mark_failed(exc.message)
            linear.save(update_fields=["status", "last_error", "updated_at"])
        return Response({"detail": exc.message, "code": exc.code}, status=status.HTTP_400_BAD_REQUEST)

    tickets = []
    for issue in issues:
        criteria = extract_criteria(issue.description)
        readiness = assess(
            issue,
            criteria,
            repository_count=repository_count,
            strategy=strategy,
            connected_repositories=connected_repositories,
        )
        tickets.append(_serialize(issue, criteria, readiness, connected_repositories))

    # Two passes, relying on sort stability: newest first within each bucket,
    # then group by state without disturbing that order.
    tickets.sort(key=lambda t: t["updatedAt"], reverse=True)
    tickets.sort(key=lambda t: STATE_ORDER.get(t["state"]["type"], 9))

    return Response(
        {
            "tickets": tickets,
            "workspace": {
                "organizationName": linear.organization_name,
                "teamNames": list(
                    linear.linear_teams.filter(selected=True).values_list("name", flat=True)
                ),
                "repositoryCount": repository_count,
                "diffScopeStrategy": strategy,
                "sourceConnected": source is not None,
            },
            "fetchedAt": timezone.now().isoformat(),
        }
    )
