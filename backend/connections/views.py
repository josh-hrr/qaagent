from __future__ import annotations

import logging

from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from .azure import AzureError
from .azure import fetch_account as fetch_azure_account
from .linear import LinearError, fetch_account
from .models import AuthMethod, Connection, LinearTeam, Provider, Repository
from .serializers import (
    AzureConnectSerializer,
    AzureSettingsSerializer,
    AzureVerifySerializer,
    ConnectionSerializer,
    LinearConnectSerializer,
    LinearTeamSelectionSerializer,
    LinearVerifySerializer,
)

log = logging.getLogger(__name__)

# Every view here is authenticated. DRF's SessionAuthentication enforces CSRF
# once a session exists, so unsafe methods are covered without the explicit
# check the signed-out sign-in endpoints need.


def _error(exc: LinearError | AzureError, http_status: int = status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"detail": exc.message, "code": exc.code}, status=http_status)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_connections(request: Request) -> Response:
    """Every configured connection, without any credentials."""
    connections = Connection.objects.prefetch_related("linear_teams", "repositories").all()
    return Response(
        {
            "connections": ConnectionSerializer(connections, many=True).data,
            # OAuth needs a registered Linear app; until then the UI shows the
            # button as unavailable rather than letting it fail on click.
            "linearOAuthConfigured": False,
            # GitHub needs a registered GitHub App. Same honest pattern.
            "githubConfigured": False,
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def verify_linear(request: Request) -> Response:
    """Check a key and list its teams — without storing anything.

    Split from connecting so the user picks teams from their real workspace
    before committing, and so a typo never leaves a broken row behind.
    """
    serializer = LinearVerifySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        account = fetch_account(serializer.validated_data["apiKey"])
    except LinearError as exc:
        return _error(exc)

    return Response(
        {
            "account": {
                "name": account.name,
                "email": account.email,
                "organizationName": account.organization_name,
            },
            "teams": [
                {"linear_id": t.id, "key": t.key, "name": t.name, "selected": False}
                for t in account.teams
            ],
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def connect_linear(request: Request) -> Response:
    """Store the key and the chosen teams.

    Re-verifies rather than trusting the earlier verify call: the two requests
    are minutes apart and the key may have been revoked in between.
    """
    serializer = LinearConnectSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    api_key = serializer.validated_data["apiKey"]
    requested_ids = set(serializer.validated_data["teamIds"])

    try:
        account = fetch_account(api_key)
    except LinearError as exc:
        return _error(exc)

    visible = {t.id: t for t in account.teams}
    unknown = requested_ids - visible.keys()
    if unknown:
        # The key cannot see these, so syncing them would fail later anyway.
        return Response(
            {
                "detail": "Some selected teams are not visible to this API key.",
                "code": "unknown_teams",
                "teamIds": sorted(unknown),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        connection, _ = Connection.objects.get_or_create(provider=Provider.LINEAR)
        connection.set_credential(api_key)
        connection.auth_method = AuthMethod.API_KEY
        connection.account_name = account.name
        connection.account_email = account.email
        connection.organization_name = account.organization_name
        connection.organization_ref = account.organization_url_key
        connection.connected_by = request.user
        connection.mark_verified()
        connection.save()

        # Replace the team list wholesale: a team removed in Linear should stop
        # appearing here, and ids are stable so selection survives.
        connection.linear_teams.exclude(linear_id__in=visible.keys()).delete()
        for team in account.teams:
            LinearTeam.objects.update_or_create(
                connection=connection,
                linear_id=team.id,
                defaults={
                    "key": team.key,
                    "name": team.name,
                    "selected": team.id in requested_ids,
                },
            )

    log.info("Linear connected by %s (%d teams)", request.user.email, len(requested_ids))
    connection.refresh_from_db()
    return Response({"connection": ConnectionSerializer(connection).data})


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_linear_teams(request: Request) -> Response:
    """Change which teams sync, without re-sending the key."""
    serializer = LinearTeamSelectionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    requested_ids = set(serializer.validated_data["teamIds"])

    connection = Connection.objects.filter(provider=Provider.LINEAR).first()
    if connection is None:
        return Response(
            {"detail": "Linear is not connected.", "code": "not_connected"},
            status=status.HTTP_404_NOT_FOUND,
        )

    known = set(connection.linear_teams.values_list("linear_id", flat=True))
    unknown = requested_ids - known
    if unknown:
        return Response(
            {
                "detail": "Some selected teams are not part of this connection.",
                "code": "unknown_teams",
                "teamIds": sorted(unknown),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    connection.linear_teams.update(selected=False)
    connection.linear_teams.filter(linear_id__in=requested_ids).update(selected=True)

    connection.refresh_from_db()
    return Response({"connection": ConnectionSerializer(connection).data})


# --- Azure DevOps ----------------------------------------------------------


def _serialize_repositories(account) -> list[dict]:
    return [
        {
            "externalId": r.id,
            "name": r.name,
            "projectName": r.project_name,
            "defaultBranch": r.default_branch,
            "webUrl": r.web_url,
            "sizeBytes": r.size_bytes,
            "selected": False,
            "lastIndexedCommit": "",
            "isIndexed": False,
        }
        for r in account.repositories
    ]


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def verify_azure(request: Request) -> Response:
    """Check a PAT and list its repositories — without storing anything."""
    serializer = AzureVerifySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        account = fetch_azure_account(data["organization"], data["pat"], data.get("project", ""))
    except AzureError as exc:
        return _error(exc)

    return Response(
        {
            "account": {
                "displayName": account.display_name,
                "email": account.email,
                "organization": account.organization,
            },
            "repositories": _serialize_repositories(account),
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def connect_azure(request: Request) -> Response:
    """Store the PAT, the chosen repositories and the diff-scope rule."""
    serializer = AzureConnectSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    requested_ids = set(data["repositoryIds"])

    try:
        account = fetch_azure_account(data["organization"], data["pat"], data.get("project", ""))
    except AzureError as exc:
        return _error(exc)

    visible = {r.id: r for r in account.repositories}
    unknown = requested_ids - visible.keys()
    if unknown:
        return Response(
            {
                "detail": "Some selected repositories are not visible to this token.",
                "code": "unknown_repositories",
                "repositoryIds": sorted(unknown),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        connection, _ = Connection.objects.get_or_create(provider=Provider.AZURE_DEVOPS)
        connection.set_credential(data["pat"])
        connection.auth_method = AuthMethod.API_KEY
        connection.account_name = account.display_name
        connection.account_email = account.email
        connection.organization_name = account.organization
        connection.organization_ref = data.get("project", "")
        connection.diff_scope_strategy = data["diffScopeStrategy"]
        connection.connected_by = request.user
        connection.mark_verified()
        connection.save()

        connection.repositories.exclude(external_id__in=list(visible.keys())).delete()
        for repo in account.repositories:
            Repository.objects.update_or_create(
                connection=connection,
                external_id=repo.id,
                defaults={
                    "name": repo.name,
                    "project_name": repo.project_name,
                    "default_branch": repo.default_branch,
                    "web_url": repo.web_url,
                    "remote_url": repo.remote_url,
                    "size_bytes": repo.size_bytes,
                    "selected": repo.id in requested_ids,
                },
            )

    log.info(
        "Azure DevOps connected by %s (%d repositories, scope=%s)",
        request.user.email, len(requested_ids), data["diffScopeStrategy"],
    )
    connection.refresh_from_db()
    return Response({"connection": ConnectionSerializer(connection).data})


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_azure_settings(request: Request) -> Response:
    """Change repository selection or the diff-scope rule, without the token."""
    serializer = AzureSettingsSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    connection = Connection.objects.filter(provider=Provider.AZURE_DEVOPS).first()
    if connection is None:
        return Response(
            {"detail": "Azure DevOps is not connected.", "code": "not_connected"},
            status=status.HTTP_404_NOT_FOUND,
        )

    if "repositoryIds" in data:
        requested_ids = set(data["repositoryIds"])
        known = set(connection.repositories.values_list("external_id", flat=True))
        unknown = requested_ids - known
        if unknown:
            return Response(
                {
                    "detail": "Some selected repositories are not part of this connection.",
                    "code": "unknown_repositories",
                    "repositoryIds": sorted(unknown),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        connection.repositories.update(selected=False)
        connection.repositories.filter(external_id__in=requested_ids).update(selected=True)

    if "diffScopeStrategy" in data:
        connection.diff_scope_strategy = data["diffScopeStrategy"]
        connection.save(update_fields=["diff_scope_strategy", "updated_at"])

    connection.refresh_from_db()
    return Response({"connection": ConnectionSerializer(connection).data})


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def disconnect_azure(request: Request) -> Response:
    """Forget the token entirely. Repositories cascade."""
    deleted, _ = Connection.objects.filter(provider=Provider.AZURE_DEVOPS).delete()
    if not deleted:
        return Response(
            {"detail": "Azure DevOps is not connected.", "code": "not_connected"},
            status=status.HTTP_404_NOT_FOUND,
        )
    log.info("Azure DevOps disconnected by %s", request.user.email)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def disconnect_linear(request: Request) -> Response:
    """Forget the key entirely. Teams cascade."""
    deleted, _ = Connection.objects.filter(provider=Provider.LINEAR).delete()
    if not deleted:
        return Response(
            {"detail": "Linear is not connected.", "code": "not_connected"},
            status=status.HTTP_404_NOT_FOUND,
        )
    log.info("Linear disconnected by %s", request.user.email)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reverify_azure(request: Request) -> Response:
    """Check the stored token again, and refresh what the repositories look like.

    A personal access token expires on its own schedule, so the only honest
    answer to "is this still working" is to ask Azure now. Selection survives:
    only metadata is refreshed.
    """
    connection = Connection.objects.filter(provider=Provider.AZURE_DEVOPS).first()
    if connection is None:
        return Response(
            {"detail": "Azure DevOps is not connected.", "code": "not_connected"},
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        account = fetch_azure_account(
            connection.organization_name, connection.credential, connection.organization_ref
        )
    except AzureError as exc:
        connection.mark_failed(exc.message)
        connection.save(update_fields=["status", "last_error", "updated_at"])
        return Response(
            {"connection": ConnectionSerializer(connection).data, "detail": exc.message, "code": exc.code},
            status=status.HTTP_200_OK,
        )

    with transaction.atomic():
        selected = set(connection.repositories.filter(selected=True).values_list("external_id", flat=True))
        visible = {r.id: r for r in account.repositories}
        # A repository that disappeared from the token's view is dropped; one
        # that appeared arrives unselected rather than silently entering scope.
        connection.repositories.exclude(external_id__in=list(visible.keys())).delete()
        for repo in account.repositories:
            Repository.objects.update_or_create(
                connection=connection,
                external_id=repo.id,
                defaults={
                    "name": repo.name,
                    "project_name": repo.project_name,
                    "default_branch": repo.default_branch,
                    "web_url": repo.web_url,
                    "remote_url": repo.remote_url,
                    "size_bytes": repo.size_bytes,
                    "selected": repo.id in selected,
                },
            )
        connection.account_name = account.display_name
        connection.account_email = account.email
        connection.mark_verified()
        connection.save()

    connection.refresh_from_db()
    return Response({"connection": ConnectionSerializer(connection).data})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reverify_linear(request: Request) -> Response:
    """Check the stored API key again and refresh the team list."""
    connection = Connection.objects.filter(provider=Provider.LINEAR).first()
    if connection is None:
        return Response(
            {"detail": "Linear is not connected.", "code": "not_connected"},
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        account = fetch_account(connection.credential)
    except LinearError as exc:
        connection.mark_failed(exc.message)
        connection.save(update_fields=["status", "last_error", "updated_at"])
        return Response(
            {"connection": ConnectionSerializer(connection).data, "detail": exc.message, "code": exc.code},
            status=status.HTTP_200_OK,
        )

    with transaction.atomic():
        selected = set(connection.linear_teams.filter(selected=True).values_list("linear_id", flat=True))
        visible = {t.id for t in account.teams}
        connection.linear_teams.exclude(linear_id__in=list(visible)).delete()
        for team in account.teams:
            LinearTeam.objects.update_or_create(
                connection=connection,
                linear_id=team.id,
                defaults={"key": team.key, "name": team.name, "selected": team.id in selected},
            )
        connection.account_name = account.name
        connection.account_email = account.email
        connection.organization_name = account.organization_name
        connection.mark_verified()
        connection.save()

    connection.refresh_from_db()
    return Response({"connection": ConnectionSerializer(connection).data})
