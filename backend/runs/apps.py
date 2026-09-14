import os
import re

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Warning, register

MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}


class RunsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "runs"
    verbose_name = "Runs"

    def ready(self) -> None:
        register(check_model_credentials)
        register(check_generation_settings)


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


def check_generation_settings(app_configs, **kwargs) -> list:
    """Catch a malformed model setting at boot instead of as a 404 mid-run.

    The failure this exists for: `.env` does not support comments on the same
    line as a value, so `LLM_MODEL=claude-haiku-4-5  # cheapest` sends the
    whole string, comment included, as the model name.
    """
    problems = []
    model = settings.LLM_MODEL
    if not MODEL_ID_RE.match(model):
        hint = "Model ids look like claude-haiku-4-5."
        if "#" in model or " " in model:
            hint = (
                "Remove anything after the model name. .env files do not support "
                "comments on the same line as a value — put comments on their own line."
            )
        problems.append(Error(f"LLM_MODEL is not a valid model id: {model!r}", hint=hint, id="runs.E001"))

    if settings.LLM_EFFORT not in EFFORT_LEVELS:
        problems.append(
            Error(
                f"LLM_EFFORT must be one of {', '.join(sorted(EFFORT_LEVELS))}: {settings.LLM_EFFORT!r}",
                hint="Put comments on their own line in .env, not after the value.",
                id="runs.E002",
            )
        )
    return problems
