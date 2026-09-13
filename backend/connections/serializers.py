from rest_framework import serializers

from .models import Connection, DiffScopeStrategy, LinearTeam, Repository


class RepositorySerializer(serializers.ModelSerializer):
    externalId = serializers.CharField(source="external_id", read_only=True)
    projectName = serializers.CharField(source="project_name", read_only=True)
    defaultBranch = serializers.CharField(source="default_branch", read_only=True)
    webUrl = serializers.CharField(source="web_url", read_only=True)
    sizeBytes = serializers.IntegerField(source="size_bytes", read_only=True)
    lastIndexedCommit = serializers.CharField(source="last_indexed_commit", read_only=True)
    isIndexed = serializers.BooleanField(source="is_indexed", read_only=True)

    class Meta:
        model = Repository
        fields = (
            "externalId", "name", "projectName", "defaultBranch",
            "webUrl", "sizeBytes", "selected", "lastIndexedCommit", "isIndexed",
        )
        read_only_fields = fields


class LinearTeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = LinearTeam
        fields = ("linear_id", "key", "name", "selected")
        read_only_fields = fields


class ConnectionSerializer(serializers.ModelSerializer):
    """Public shape of a connection.

    ``encrypted_credential`` is deliberately absent: the credential must never
    leave the server, so it is not in ``fields`` and cannot be leaked by adding
    one carelessly later. ``credential_hint`` is the only hint a client gets.
    """

    authMethod = serializers.CharField(source="auth_method", read_only=True)
    credentialHint = serializers.CharField(source="credential_hint", read_only=True)
    accountName = serializers.CharField(source="account_name", read_only=True)
    accountEmail = serializers.CharField(source="account_email", read_only=True)
    organizationName = serializers.CharField(source="organization_name", read_only=True)
    lastVerifiedAt = serializers.DateTimeField(source="last_verified_at", read_only=True)
    lastError = serializers.CharField(source="last_error", read_only=True)
    diffScopeStrategy = serializers.CharField(source="diff_scope_strategy", read_only=True)
    connectedBy = serializers.SerializerMethodField()
    teams = serializers.SerializerMethodField()
    repositories = serializers.SerializerMethodField()

    class Meta:
        model = Connection
        fields = (
            "provider", "authMethod", "credentialHint", "status",
            "accountName", "accountEmail", "organizationName", "organizationRef",
            "diffScopeStrategy", "lastVerifiedAt", "lastError", "connectedBy",
            "teams", "repositories",
        )
        read_only_fields = fields

    organizationRef = serializers.CharField(source="organization_ref", read_only=True)

    def get_connectedBy(self, obj) -> str:
        return obj.connected_by.email if obj.connected_by else ""

    def get_teams(self, obj) -> list:
        if obj.provider != "linear":
            return []
        return LinearTeamSerializer(obj.linear_teams.all(), many=True).data

    def get_repositories(self, obj) -> list:
        if obj.provider not in ("azure_devops", "github"):
            return []
        return RepositorySerializer(obj.repositories.all(), many=True).data


class LinearVerifySerializer(serializers.Serializer):
    apiKey = serializers.CharField(max_length=512, trim_whitespace=True, write_only=True)

    def validate_apiKey(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter your Linear API key.")
        # Catch an obvious paste mistake before spending a network round trip.
        if not value.startswith("lin_"):
            raise serializers.ValidationError(
                "That does not look like a Linear API key — they start with 'lin_api_'."
            )
        return value


class LinearConnectSerializer(LinearVerifySerializer):
    teamIds = serializers.ListField(
        child=serializers.CharField(max_length=64),
        allow_empty=False,
        max_length=100,
    )


class LinearTeamSelectionSerializer(serializers.Serializer):
    teamIds = serializers.ListField(
        child=serializers.CharField(max_length=64),
        allow_empty=False,
        max_length=100,
    )


# --- Azure DevOps ----------------------------------------------------------


class AzureVerifySerializer(serializers.Serializer):
    organization = serializers.CharField(max_length=200, trim_whitespace=True)
    project = serializers.CharField(
        max_length=128, trim_whitespace=True, required=False, allow_blank=True, default=""
    )
    pat = serializers.CharField(max_length=512, trim_whitespace=True, write_only=True)

    def validate_pat(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter a personal access token.")
        return value


class AzureConnectSerializer(AzureVerifySerializer):
    repositoryIds = serializers.ListField(
        child=serializers.CharField(max_length=128),
        allow_empty=False,
        max_length=200,
    )
    diffScopeStrategy = serializers.ChoiceField(
        choices=DiffScopeStrategy.choices,
        default=DiffScopeStrategy.LINKED_PR,
    )


class AzureSettingsSerializer(serializers.Serializer):
    """Change selection or strategy without re-sending the token."""

    repositoryIds = serializers.ListField(
        child=serializers.CharField(max_length=128),
        allow_empty=False,
        max_length=200,
        required=False,
    )
    diffScopeStrategy = serializers.ChoiceField(
        choices=DiffScopeStrategy.choices, required=False
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Nothing to update.")
        return attrs
