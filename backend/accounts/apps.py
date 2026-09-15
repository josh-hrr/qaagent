from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Warning, register

# The value settings.py falls back to when DJANGO_SECRET_KEY is unset.
INSECURE_SECRET_KEY = "dev-only-insecure-key-change-me"


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Accounts"

    def ready(self) -> None:
        # A deploy check: it describes how this is *served*, so it runs with
        # `manage.py check --deploy` and never blocks a test run or runserver.
        register(check_sign_in_policy, "security", deploy=True)


def check_sign_in_policy(app_configs, **kwargs):
    """Refuse to run outside development with a forgeable key or open sign-up.

    Both are silent failures otherwise: a default SECRET_KEY lets anyone who has
    read the source mint a session cookie, and an empty domain allow-list means
    any address that receives a magic link becomes a user of this workspace —
    with access to the Linear key, the repositories and the model spend.
    """
    if settings.DEBUG:
        return []

    problems = []
    if settings.SECRET_KEY == INSECURE_SECRET_KEY:
        problems.append(
            Error(
                "DJANGO_SECRET_KEY is still the development default, which is public in the source tree.",
                hint="Set DJANGO_SECRET_KEY in the environment to a long random value.",
                id="accounts.E001",
            )
        )
    if not settings.ALLOWED_EMAIL_DOMAINS:
        problems.append(
            Warning(
                "ALLOWED_EMAIL_DOMAINS is empty: anyone who can reach this server can sign themselves in.",
                hint="Set ALLOWED_EMAIL_DOMAINS to the company domains that may sign in.",
                id="accounts.W001",
            )
        )
    return problems
