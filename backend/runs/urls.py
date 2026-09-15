from django.urls import path

from . import export_views, review, views

app_name = "runs"

urlpatterns = [
    path("", views.list_runs, name="list"),
    path("start/", views.start_run, name="start"),
    path("<int:run_id>/", views.run_detail, name="detail"),
    path("<int:run_id>/cancel/", views.cancel_run, name="cancel"),
    # Screen 06 — review
    path("<int:run_id>/review/", review.review, name="review"),
    path("<int:run_id>/drift/", review.drift, name="drift"),
    path("<int:run_id>/test-cases/bulk/", review.bulk_test_cases, name="bulk-test-cases"),
    path("<int:run_id>/test-cases/<int:number>/", review.test_case, name="test-case"),
    path("<int:run_id>/findings/<int:finding_id>/test-case/", review.finding_to_test_case, name="finding-to-test-case"),
    path("<int:run_id>/findings/<int:finding_id>/dismiss/", review.dismiss_finding, name="dismiss-finding"),
    path("<int:run_id>/ambiguities/<int:ambiguity_id>/answer/", review.answer_ambiguity, name="answer-ambiguity"),
    # Screen 07 — export
    path("<int:run_id>/export/preview/", export_views.export_preview, name="export-preview"),
    path("<int:run_id>/export/download/", export_views.export_download, name="export-download"),
]
