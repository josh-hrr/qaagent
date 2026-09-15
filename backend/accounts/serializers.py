from rest_framework import serializers

from .models import User
from .services import email_domain_allowed


class UserSerializer(serializers.ModelSerializer):
    displayName = serializers.CharField(source="display_name", read_only=True)
    fullName = serializers.CharField(source="full_name", read_only=True)
    jobTitle = serializers.CharField(source="job_title", read_only=True)
    avatarUrl = serializers.CharField(source="avatar_url", read_only=True)
    initials = serializers.CharField(read_only=True)
    # Last export choices, so the dialog opens where this user left it.
    exportPreferences = serializers.JSONField(source="export_preferences", read_only=True)

    class Meta:
        model = User
        fields = (
            "id", "email", "fullName", "displayName", "initials", "jobTitle", "avatarUrl",
            "exportPreferences",
        )
        read_only_fields = fields


class MagicLinkRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if not email_domain_allowed(value):
            # Refusing here is deliberate: the domain allowlist is public policy,
            # not a secret, and a clear message beats a silent no-op.
            raise serializers.ValidationError(
                "That email domain is not allowed to sign in to this workspace."
            )
        return value


class MagicLinkVerifySerializer(serializers.Serializer):
    token = serializers.CharField(max_length=512, trim_whitespace=True)
