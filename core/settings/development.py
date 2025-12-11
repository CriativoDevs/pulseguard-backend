# Development settings
from .base import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "*.local"]

# SQLite default for DEV
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Email Backend for DEV
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Disable CSRF for DEV (only for development!)
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
]

# REST Framework extra settings for DEV
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = (
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
)
