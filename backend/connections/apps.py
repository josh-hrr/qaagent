from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Warning, register


class ConnectionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "connections"
    verbose_name = "Connections"

    def ready(self) -> None:
        register(check_credential_encryption_key)


def check_credential_encryption_key(app_configs, **kwargs) -> list:
    """Fail loudly at startup rather than on the first save.

    A bad key used to surface as a 500 the first time someone pressed "Connect
    Linear" — long after the mistake was made. `manage.py check` and `runserver`
    run this, so a broken or missing key is caught before anyone sees it.
    """
    from cryptography.fernet import Fernet

    from .crypto import DEV_KEY

    key = getattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "") or ""

    if not key:
        if settings.DEBUG:
            return [
                Warning(
                    "CREDENTIAL_ENCRYPTION_KEY is not set — using the development "
                    "fallback key, which is committed to the repository.",
                    hint="Generate one with: python manage.py generate_encryption_key",
                    id="connections.W001",
                )
            ]
        return [
            Error(
                "CREDENTIAL_ENCRYPTION_KEY must be set outside development.",
                hint="Generate one with: python manage.py generate_encryption_key",
                id="connections.E001",
            )
        ]

    try:
        Fernet(key.encode())
    except (ValueError, TypeError):
        return [
            Error(
                "CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key. It must be "
                "44 characters of url-safe base64 (32 bytes), including the "
                "trailing '='.",
                hint="Generate one with: python manage.py generate_encryption_key",
                id="connections.E002",
            )
        ]

    if key == DEV_KEY and not settings.DEBUG:
        return [
            Error(
                "CREDENTIAL_ENCRYPTION_KEY is the development fallback key, which "
                "is public in the source tree.",
                hint="Generate a real one: python manage.py generate_encryption_key",
                id="connections.E003",
            )
        ]

    return []
