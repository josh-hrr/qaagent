"""Workspace settings, as a person using the product should see them.

Most of what governs a run — the model, the limits, the sign-in policy — is
fixed when the workspace is deployed. This endpoint reports those as plain
facts, in the words a tester would use, and says who to ask to change them. It
deliberately exposes no variable names, no file paths and no check output:
that is operator detail, and a reader of this screen is not the operator.

What a person genuinely owns — their own export defaults — is writable here.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from runs import exporting
from runs.views import monthly_spend

# Model ids are not names a tester should have to decode.
MODELS = {
    "claude-opus-5": ("Claude Opus 5", "Strongest at following a change across files."),
    "claude-sonnet-5": ("Claude Sonnet 5", "A middle ground on cost and depth."),
    "claude-haiku-4-5": ("Claude Haiku 4.5", "Fastest and cheapest; less thorough on wide changes."),
}

EFFORT_NOTES = {
    "low": "Shallow reading — cheapest, and likeliest to miss a knock-on effect.",
    "medium": "Reads the obvious dependencies of a change.",
    "high": "Follows a change into what it affects. The default.",
    "xhigh": "Explores further before writing, at a higher cost per run.",
    "max": "Explores as far as the limits allow.",
}


def _hours(value: int) -> str:
    if value % 24 == 0 and value >= 24:
        days = value // 24
        return f"{days} day{'s' if days != 1 else ''}"
    return f"{value} hour{'s' if value != 1 else ''}"


class ExportDefaultsSerializer(serializers.Serializer):
    fileFormat = serializers.ChoiceField(choices=exporting.FORMATS)
    layout = serializers.ChoiceField(choices=exporting.LAYOUTS)
    columns = serializers.ListField(
        child=serializers.ChoiceField(choices=exporting.COLUMN_KEYS),
        allow_empty=False,
        max_length=len(exporting.COLUMN_KEYS),
    )
    options = serializers.DictField(child=serializers.BooleanField(), allow_empty=True)

    def validate_options(self, value: dict) -> dict:
        unknown = set(value) - set(exporting.OPTION_KEYS)
        if unknown:
            raise serializers.ValidationError(f"Unknown options: {', '.join(sorted(unknown))}.")
        return value


def _export_defaults(user) -> dict:
    stored = user.export_preferences or {}
    return {
        "fileFormat": stored.get("fileFormat", "csv"),
        "layout": stored.get("layout", "table"),
        "columns": stored.get("columns") or list(exporting.DEFAULT_COLUMNS),
        "options": {key: (stored.get("options") or {}).get(key, exporting.DEFAULT_OPTIONS[key])
                    for key in exporting.OPTION_KEYS},
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def workspace_settings(request: Request) -> Response:
    model = settings.LLM_MODEL
    name, note = MODELS.get(model, (model, ""))
    effort = settings.LLM_EFFORT
    domains = settings.ALLOWED_EMAIL_DOMAINS

    return Response(
        {
            "spend": monthly_spend(),
            "generation": {
                "model": model,
                "modelName": name,
                "modelNote": note,
                "effort": effort,
                "effortNote": EFFORT_NOTES.get(effort, ""),
                "costCapUsd": f"{settings.RUN_COST_CAP_USD:.2f}",
                "maxFiles": settings.RUN_MAX_FILES,
                "maxRounds": settings.RUN_MAX_ROUNDS,
            },
            "signIn": {
                "allowedEmailDomains": domains,
                # Phrased, not raw: "12 hours" reads; 43200 does not.
                "idleTimeout": _hours(settings.SESSION_IDLE_TIMEOUT_HOURS),
                "absoluteTimeout": _hours(settings.SESSION_ABSOLUTE_TIMEOUT_HOURS),
                "magicLinkMinutes": settings.MAGIC_LINK_TTL_MINUTES,
            },
            "exportDefaults": _export_defaults(request.user),
            "exportColumns": [
                {"key": column.key, "header": column.header, "required": column.required}
                for column in exporting.COLUMNS
            ],
            "account": {
                "email": request.user.email,
                "displayName": request.user.display_name,
                "joined": request.user.date_joined.isoformat(),
            },
        }
    )


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_export_defaults(request: Request) -> Response:
    """The one thing on this screen a person owns outright."""
    serializer = ExportDefaultsSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    required = set(exporting.REQUIRED_KEYS)
    request.user.export_preferences = {
        "fileFormat": data["fileFormat"],
        "layout": data["layout"],
        "scope": (request.user.export_preferences or {}).get("scope", "all"),
        "columns": [key for key in exporting.COLUMN_KEYS if key in set(data["columns"]) | required],
        "options": {key: data["options"].get(key, exporting.DEFAULT_OPTIONS[key]) for key in exporting.OPTION_KEYS},
    }
    request.user.save(update_fields=["export_preferences"])
    return Response({"exportDefaults": _export_defaults(request.user)}, status=status.HTTP_200_OK)
