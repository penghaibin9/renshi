"""Production security gates and secure defaults."""

from django.core.exceptions import ImproperlyConfigured

INSECURE_SECRET_KEYS = frozenset(
    {
        "django-insecure-default-key",
        "dev-secret-key-change-in-production",
        "change-me",
        "django-insecure-j8op9)1q8$1&0^s&p*_0%d#pr@w9qj@1o=3#@d=a(^@9@zd@%j",
    }
)

INSECURE_DB_INIT_PASSWORDS = frozenset(
    {
        "d3f6a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d",
        "dev-init-password-change-in-production",
        "change-me-db-init-password",
    }
)


def is_production_mode(debug: bool, horilla_env: str) -> bool:
    explicit_production = (horilla_env or "").strip().lower() == "production"
    if explicit_production and debug:
        raise ImproperlyConfigured(
            "Horilla production security check failed:\n- "
            "HORILLA_ENV=production cannot run with DEBUG=True."
        )
    return (not debug) or explicit_production


def validate_production_secrets(secret_key, allowed_hosts, db_init_password):
    errors = []

    if not secret_key or secret_key in INSECURE_SECRET_KEYS:
        errors.append(
            "SECRET_KEY is missing or uses a known insecure default. Generate a unique key."
        )
    elif secret_key.startswith("django-insecure-") or secret_key.startswith(
        "change-me"
    ):
        errors.append("SECRET_KEY still uses a placeholder value.")

    hosts = list(allowed_hosts or [])
    if not hosts or hosts == ["*"] or set(hosts) == {"*"}:
        errors.append("ALLOWED_HOSTS must contain real hostnames, not '*'.")

    if not db_init_password or db_init_password in INSECURE_DB_INIT_PASSWORDS:
        errors.append("DB_INIT_PASSWORD must be replaced before production.")

    if errors:
        raise ImproperlyConfigured(
            "Horilla production security check failed:\n- " + "\n- ".join(errors)
        )


def apply_secure_defaults(env, debug: bool) -> dict:
    settings = {
        "SESSION_COOKIE_SECURE": True,
        "CSRF_COOKIE_SECURE": True,
        "SECURE_CONTENT_TYPE_NOSNIFF": True,
        "SECURE_REFERRER_POLICY": "strict-origin-when-cross-origin",
        "SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https"),
        "SECURE_SSL_REDIRECT": env.bool("SECURE_SSL_REDIRECT", default=False),
    }
    if settings["SECURE_SSL_REDIRECT"]:
        settings["SECURE_HSTS_SECONDS"] = env.int(
            "SECURE_HSTS_SECONDS", default=31536000
        )
        settings["SECURE_HSTS_INCLUDE_SUBDOMAINS"] = True
        settings["SECURE_HSTS_PRELOAD"] = True
    return settings
