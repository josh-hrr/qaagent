"""Django settings for the QA Agent backend.

Configuration comes from environment variables (see ``.env.example``). The only
value that must be set outside development is ``DJANGO_SECRET_KEY``.
"""

from pathlib import Path

import environ
from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    # Turn on only when a load balancer or reverse proxy sets X-Forwarded-Proto.
    TRUST_PROXY_SSL_HEADER=(bool, False),
    FRONTEND_ORIGIN=(str, "http://localhost:5173"),
    FRONTEND_URL=(str, "http://localhost:5173"),
    # Sessions: idle expiry slides with activity, the absolute cap does not.
    SESSION_IDLE_TIMEOUT_HOURS=(int, 12),
    SESSION_ABSOLUTE_TIMEOUT_HOURS=(int, 24 * 7),
    # Sign-in policy
    ALLOWED_EMAIL_DOMAINS=(list, []),
    MAGIC_LINK_TTL_MINUTES=(int, 15),
    MAGIC_LINK_MAX_PER_EMAIL_PER_HOUR=(int, 5),
    MAGIC_LINK_MAX_PER_IP_PER_HOUR=(int, 20),
    # Encrypts third-party credentials at rest. Separate from SECRET_KEY on
    # purpose: rotating SECRET_KEY signs everyone out and must not also make
    # every stored Linear/Azure credential unreadable.
    CREDENTIAL_ENCRYPTION_KEY=(str, ""),
    # SSO — a provider counts as configured only when both id and secret are set
    MICROSOFT_CLIENT_ID=(str, ""),
    MICROSOFT_CLIENT_SECRET=(str, ""),
    MICROSOFT_TENANT_ID=(str, ""),
    GOOGLE_CLIENT_ID=(str, ""),
    GOOGLE_CLIENT_SECRET=(str, ""),
)

environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-insecure-key-change-me")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "accounts",
    "connections",
    "tickets",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.AbsoluteSessionTimeoutMiddleware",  # needs request.user
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- API -------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

# --- Session / CSRF --------------------------------------------------------
# The SPA authenticates with an httpOnly session cookie. No token is ever
# readable from JavaScript, which is also what the product itself tests for.

# The __Host- prefix is enforced by the browser: the cookie must be Secure, carry
# no Domain attribute and be scoped to Path=/. That stops a compromised sibling
# subdomain from writing or overwriting our cookies. It requires Secure, so the
# plain names stay in development where there is no TLS.
_HOST_PREFIX = "" if DEBUG else "__Host-"

SESSION_COOKIE_NAME = f"{_HOST_PREFIX}qaagent_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = env("SESSION_IDLE_TIMEOUT_HOURS") * 3600
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True  # sliding — pairs with the absolute cap below

# Hard ceiling on a session's total life, counted from sign-in and unaffected by
# activity. Without it the sliding expiry above means a session that is used
# daily never ends — including one an attacker is keeping warm with a stolen
# cookie. Enforced by accounts.middleware.AbsoluteSessionTimeoutMiddleware.
SESSION_ABSOLUTE_TIMEOUT = env("SESSION_ABSOLUTE_TIMEOUT_HOURS") * 3600

CSRF_COOKIE_NAME = f"{_HOST_PREFIX}qaagent_csrftoken"
CSRF_COOKIE_HTTPONLY = False  # the SPA reads it to echo in the X-CSRFToken header
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
CSRF_TRUSTED_ORIGINS = [env("FRONTEND_ORIGIN")]

# In development the Vite dev server proxies /api to Django, so requests are
# same-origin and CORS is not exercised. It stays configured for setups that
# serve the two apps from different hosts.
CORS_ALLOWED_ORIGINS = [env("FRONTEND_ORIGIN")]
CORS_ALLOW_CREDENTIALS = True

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# HTTPS. The __Host- cookie prefix already requires TLS everywhere outside
# development, so these only make that explicit.
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000  # one year
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
# Preload is deliberately off: submitting to the browser preload list is
# effectively irreversible, so it should be a conscious decision, not a default.
SECURE_HSTS_PRELOAD = False

# Only trust a forwarded-protocol header when something in front of Django is
# actually setting it. Trusting it unconditionally lets a client claim HTTPS and
# defeat SECURE_SSL_REDIRECT and the Secure cookie flags.
if env("TRUST_PROXY_SSL_HEADER"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# CSP for responses Django serves — the JSON API and the admin. The SPA's own
# CSP is injected into index.html at build time (see frontend/vite.config.ts),
# because Django never serves that document.
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF],
    # The bundled Django admin ships inline styles; nothing else here needs this.
    "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
    "img-src": [CSP.SELF, "data:"],
    "connect-src": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "object-src": [CSP.NONE],
}

# --- Email -----------------------------------------------------------------
# Development prints magic links to the console; set EMAIL_URL for real sending.

vars().update(env.email_url("EMAIL_URL", default="consolemail://"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="QA Agent <qa-agent@localhost>")

# --- Sign-in policy --------------------------------------------------------

FRONTEND_URL = env("FRONTEND_URL").rstrip("/")
ALLOWED_EMAIL_DOMAINS = [d.lower().lstrip("@") for d in env("ALLOWED_EMAIL_DOMAINS") if d]
MAGIC_LINK_TTL_MINUTES = env("MAGIC_LINK_TTL_MINUTES")
MAGIC_LINK_MAX_PER_EMAIL_PER_HOUR = env("MAGIC_LINK_MAX_PER_EMAIL_PER_HOUR")
MAGIC_LINK_MAX_PER_IP_PER_HOUR = env("MAGIC_LINK_MAX_PER_IP_PER_HOUR")

CREDENTIAL_ENCRYPTION_KEY = env("CREDENTIAL_ENCRYPTION_KEY")

SSO_PROVIDERS = {
    "microsoft": {
        "label": "Microsoft Entra ID",
        "client_id": env("MICROSOFT_CLIENT_ID"),
        "client_secret": env("MICROSOFT_CLIENT_SECRET"),
        "tenant_id": env("MICROSOFT_TENANT_ID"),
    },
    "google": {
        "label": "Google Workspace",
        "client_id": env("GOOGLE_CLIENT_ID"),
        "client_secret": env("GOOGLE_CLIENT_SECRET"),
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
