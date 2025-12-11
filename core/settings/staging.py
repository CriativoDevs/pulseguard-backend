# Staging settings
from .base import *

DEBUG = False
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="staging.example.com", cast=Csv())

# PostgreSQL for Staging
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="pulseguard_stg"),
        "USER": config("DB_USER", default="postgres"),
        "PASSWORD": config("DB_PASSWORD", default=""),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

# Email Backend for Staging
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("SMTP_HOST", default="localhost")
EMAIL_PORT = config("SMTP_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("SMTP_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("SMTP_USER", default="")
EMAIL_HOST_PASSWORD = config("SMTP_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("SMTP_FROM", default="noreply@pulseguard.local")

# Security settings for Staging
SECURE_SSL_REDIRECT = False  # Use reverse proxy for SSL
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False

# REST Framework settings for Staging
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = ("rest_framework.renderers.JSONRenderer",)
