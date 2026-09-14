import os

from django.apps import AppConfig
from django.core.checks import Warning, register


class RunsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "runs"
    verbose_name = "Runs"

    def ready(self) -> None:
        register(check_model_credentials)


def check_model_credentials(app_configs, **kwargs) -> list:
    """Warn at startup, not on the first Generate click, when no key is set."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return []
    return [
        Warning(
            "ANTHROPIC_API_KEY is not set — test case generation will fail.",
            hint="Add ANTHROPIC_API_KEY to backend/.env. Never commit it.",
            id="runs.W001",
        )
    ]
