from django.contrib import admin

from .models import Connection, LinearTeam


class LinearTeamInline(admin.TabularInline):
    model = LinearTeam
    extra = 0
    fields = ("key", "name", "selected", "linear_id")
    readonly_fields = ("key", "name", "linear_id")


@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = (
        "provider", "status", "organization_name", "account_email",
        "credential_hint", "last_verified_at",
    )
    list_filter = ("provider", "status")
    inlines = [LinearTeamInline]
    # encrypted_credential is excluded entirely: the admin is a browser page,
    # and there is no reason for a live third-party credential to travel there.
    exclude = ("encrypted_credential",)
    readonly_fields = (
        "provider", "auth_method", "credential_hint", "account_name", "account_email",
        "organization_name", "organization_ref", "status", "last_verified_at",
        "last_error", "connected_by", "created_at", "updated_at",
    )

    def has_add_permission(self, request) -> bool:
        return False
