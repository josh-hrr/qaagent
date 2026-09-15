"""Screen 07: preview an export, then download it.

Both endpoints read the same settings and call the same renderer, so the
preview in the dialog is the file, not an impression of it. Choices that are
worth keeping (format, columns, toggles) are written back to the user on
download — the point where we know they were actually used.
"""

from __future__ import annotations

import logging

from django.http import HttpResponse
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import exporting
from .models import ExportRecord, Run, RunStatus, TestCaseStatus
from .review import _reviewable

log = logging.getLogger(__name__)


class ExportSettingsSerializer(serializers.Serializer):
    fileFormat = serializers.ChoiceField(choices=exporting.FORMATS, default="csv")
    layout = serializers.ChoiceField(choices=exporting.LAYOUTS, default="table")
    scope = serializers.ChoiceField(choices=exporting.SCOPES, default="all")
    columns = serializers.ListField(
        child=serializers.ChoiceField(choices=exporting.COLUMN_KEYS),
        allow_empty=True,
        max_length=len(exporting.COLUMN_KEYS),
        default=list,
    )
    caseNumbers = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=True, max_length=1000, default=list
    )
    numberedSteps = serializers.BooleanField(default=True)
    blankActual = serializers.BooleanField(default=True)
    runHeader = serializers.BooleanField(default=False)

    def to_settings(self) -> exporting.ExportSettings:
        data = self.validated_data
        return exporting.ExportSettings(
            file_format=data["fileFormat"],
            layout=data["layout"],
            scope=data["scope"],
            columns=data["columns"] or list(exporting.DEFAULT_COLUMNS),
            case_numbers=data["caseNumbers"],
            options={
                "numbered_steps": data["numberedSteps"],
                "blank_actual": data["blankActual"],
                "run_header": data["runHeader"],
            },
        )


def _settings_from(request: Request) -> exporting.ExportSettings:
    """Parse the query string. Lists arrive comma-separated, booleans as 0/1."""
    query = request.query_params
    payload = {
        "fileFormat": query.get("fileFormat", "csv"),
        "layout": query.get("layout", "table"),
        "scope": query.get("scope", "all"),
        "columns": [c for c in query.get("columns", "").split(",") if c],
        "caseNumbers": [n for n in query.get("caseNumbers", "").split(",") if n.strip().isdigit()],
        "numberedSteps": query.get("numberedSteps", "1"),
        "blankActual": query.get("blankActual", "1"),
        "runHeader": query.get("runHeader", "0"),
    }
    serializer = ExportSettingsSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    return serializer.to_settings()


def _not_exportable(run: Run) -> Response | None:
    if run.status != RunStatus.SUCCEEDED:
        return Response(
            {"detail": "Only a finished run can be exported.", "code": "run_not_finished"},
            status=status.HTTP_409_CONFLICT,
        )
    return None


def _counts(run: Run) -> dict:
    cases = run.test_cases.exclude(status=TestCaseStatus.REJECTED)
    return {
        "all": cases.count(),
        "approved": cases.filter(status=TestCaseStatus.APPROVED).count(),
        "rejectedExcluded": run.test_cases.filter(status=TestCaseStatus.REJECTED).count(),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def export_preview(request: Request, run_id: int) -> Response:
    run = _reviewable(run_id)
    if blocked := _not_exportable(run):
        return blocked

    settings = _settings_from(request)
    cases = exporting.select_cases(run, settings)
    # Built in full, not estimated: the size shown is the size downloaded.
    payload, _ = exporting.build(run, cases, settings)

    return Response(
        {
            "preview": exporting.preview(run, cases, settings),
            "filename": exporting.filename(run, settings),
            "byteSize": len(payload),
            "caseCount": len(cases),
            "counts": _counts(run),
            "columns": [
                {"key": c.key, "header": c.header, "required": c.required} for c in exporting.COLUMNS
            ],
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def export_download(request: Request, run_id: int) -> HttpResponse:
    run = _reviewable(run_id)
    if blocked := _not_exportable(run):
        return blocked

    settings = _settings_from(request)
    cases = exporting.select_cases(run, settings)
    if not cases:
        return Response(
            {"detail": "There are no test cases to export with those settings.", "code": "nothing_to_export"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    payload, content_type = exporting.build(run, cases, settings)
    name = exporting.filename(run, settings)

    ExportRecord.objects.create(
        run=run,
        exported_by=request.user,
        file_format=settings.file_format,
        layout=settings.layout if settings.file_format == "md" else "",
        scope=settings.scope,
        columns=[c.key for c in settings.active],
        options=settings.options,
        case_numbers=[c.number for c in cases],
        filename=name,
        byte_size=len(payload),
    )
    # Remembered here rather than on every preview keystroke: this is the
    # moment the settings were actually used for something.
    request.user.export_preferences = settings.as_preferences()
    request.user.save(update_fields=["export_preferences"])

    log.info("Run %s exported as %s (%d cases) by %s", run.pk, name, len(cases), request.user.email)

    response = HttpResponse(payload, content_type=content_type)
    # The quoted filename is what the browser saves it as.
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    response["Content-Length"] = str(len(payload))
    # A download is per-user and per-run; never let a proxy hand it to someone else.
    response["Cache-Control"] = "private, no-store"
    return response
