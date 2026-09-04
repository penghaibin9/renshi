"""Production security gates and secure defaults."""

import base64
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from django.core.validators import validate_email

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


def _is_placeholder(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return (
        not normalized
        or normalized.startswith(("change-me", "replace-with"))
        or normalized in {"password", "secret", "renshi_pass", "renshi_password"}
    )


def _host_is_allowed(hostname: str, allowed_hosts) -> bool:
    hostname = str(hostname or "").lower().rstrip(".")
    for allowed in allowed_hosts:
        allowed = str(allowed or "").lower().strip().rstrip(".")
        if hostname == allowed:
            return True
        if allowed.startswith(".") and hostname.endswith(allowed):
            return True
        if allowed.startswith("*.") and hostname.endswith(allowed[1:]):
            return True
    return False


def validate_production_secrets(
    secret_key,
    allowed_hosts,
    db_init_password,
    *,
    csrf_trusted_origins=(),
    database_password="",
    redis_url="",
    redis_password="",
    backup_encryption_key="",
):
    errors = []

    if not secret_key or secret_key in INSECURE_SECRET_KEYS:
        errors.append(
            "SECRET_KEY is missing or uses a known insecure default. Generate a unique key."
        )
    elif secret_key.startswith("django-insecure-") or secret_key.startswith(
        "change-me"
    ):
        errors.append("SECRET_KEY still uses a placeholder value.")
    elif len(secret_key) < 50:
        errors.append("SECRET_KEY must contain at least 50 characters in production.")
    elif len(set(secret_key)) < 12:
        errors.append(
            "SECRET_KEY has insufficient character diversity for production."
        )

    hosts = list(allowed_hosts or [])
    if not hosts or hosts == ["*"] or set(hosts) == {"*"}:
        errors.append("ALLOWED_HOSTS must contain real hostnames, not '*'.")

    if not db_init_password or db_init_password in INSECURE_DB_INIT_PASSWORDS:
        errors.append("DB_INIT_PASSWORD must be replaced before production.")

    if _is_placeholder(database_password):
        errors.append("The application database password is missing or insecure.")

    origins = list(csrf_trusted_origins or [])
    if not origins:
        errors.append("CSRF_TRUSTED_ORIGINS must contain the public HTTPS origin.")
    for origin in origins:
        parsed = urlsplit(str(origin))
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            errors.append(
                f"CSRF_TRUSTED_ORIGINS contains an invalid production origin: {origin!r}."
            )
        elif not _host_is_allowed(parsed.hostname, hosts):
            errors.append(
                f"CSRF trusted host {parsed.hostname!r} is not covered by ALLOWED_HOSTS."
            )

    parsed_redis = urlsplit(str(redis_url or ""))
    if parsed_redis.scheme not in {"redis", "rediss"} or not parsed_redis.hostname:
        errors.append("REDIS_URL must be a valid redis:// or rediss:// URL.")
    elif _is_placeholder(parsed_redis.password):
        errors.append("REDIS_URL must contain a non-placeholder password.")

    if _is_placeholder(redis_password):
        errors.append("REDIS_PASSWORD must be replaced before production.")
    elif parsed_redis.password and parsed_redis.password != str(redis_password):
        errors.append("REDIS_PASSWORD must match the password embedded in REDIS_URL.")

    if _is_placeholder(backup_encryption_key) or len(
        str(backup_encryption_key).encode("utf-8")
    ) < 32:
        errors.append(
            "PRODUCTION_BACKUP_ENCRYPTION_KEY must contain at least 32 non-placeholder bytes."
        )

    if errors:
        raise ImproperlyConfigured(
            "Horilla production security check failed:\n- " + "\n- ".join(errors)
        )


def validate_malware_scanner_configuration(
    *, required, host, port, timeout_seconds, max_bytes, production=False
):
    """Validate the fail-closed upload security boundary."""

    errors = []
    if production and not required:
        errors.append("MALWARE_SCAN_REQUIRED must be enabled in production.")
    if required and not str(host or "").strip():
        errors.append("MALWARE_SCAN_HOST is required when malware scanning is enabled.")
    try:
        valid_port = 1 <= int(port) <= 65535
    except (TypeError, ValueError):
        valid_port = False
    if required and not valid_port:
        errors.append("MALWARE_SCAN_PORT must be a valid TCP port.")
    try:
        valid_timeout = 0 < float(timeout_seconds) <= 60
    except (TypeError, ValueError):
        valid_timeout = False
    if required and not valid_timeout:
        errors.append("MALWARE_SCAN_TIMEOUT_SECONDS must be between 0 and 60 seconds.")
    try:
        valid_limit = 1024 <= int(max_bytes) <= 50 * 1024 * 1024
    except (TypeError, ValueError):
        valid_limit = False
    if required and not valid_limit:
        errors.append("MALWARE_SCAN_MAX_BYTES must be between 1 KiB and 50 MiB.")
    if errors:
        raise ImproperlyConfigured(
            "Horilla malware scanner configuration check failed:\n- "
            + "\n- ".join(errors)
        )


def validate_hr04_privacy_configuration(
    *, notice_version, retention_days, privacy_contact, material_max_bytes, scan_max_bytes
):
    """Reject a public recruitment notice that cannot identify its real policy."""
    errors = []
    version = str(notice_version or "").strip()
    contact = str(privacy_contact or "").strip()
    if not version or len(version) > 32:
        errors.append("HR04_PRIVACY_NOTICE_VERSION must contain 1 to 32 characters.")
    try:
        valid_retention = 30 <= int(retention_days) <= 36500
    except (TypeError, ValueError):
        valid_retention = False
    if not valid_retention:
        errors.append("HR04_CANDIDATE_RETENTION_DAYS must be between 30 and 36500.")
    if (
        not contact
        or contact == "招聘公告公布的联系方式"
        or "example.edu.cn" in contact.lower()
        or contact.lower().startswith(("change-me", "replace-with"))
    ):
        errors.append("HR04_PRIVACY_CONTACT must contain the school's real rights channel.")
    try:
        material_limit = int(material_max_bytes)
        scan_limit = int(scan_max_bytes)
        valid_material_limit = 1024 <= material_limit <= scan_limit
    except (TypeError, ValueError):
        valid_material_limit = False
    if not valid_material_limit:
        errors.append(
            "HR04_APPLICATION_MATERIAL_MAX_BYTES must be between 1 KiB and MALWARE_SCAN_MAX_BYTES."
        )
    if errors:
        raise ImproperlyConfigured(
            "Horilla HR04 privacy configuration check failed:\n- "
            + "\n- ".join(errors)
        )


def validate_login_security_configuration(
    *, max_attempts, ip_max_attempts, attempt_window, ban_time, remember_seconds
):
    """Reject lockout/session settings that are unsafe for a shared campus network."""

    errors = []
    try:
        max_attempts = int(max_attempts)
    except (TypeError, ValueError):
        max_attempts = 0
    try:
        ip_max_attempts = int(ip_max_attempts)
    except (TypeError, ValueError):
        ip_max_attempts = 0
    try:
        attempt_window = int(attempt_window)
    except (TypeError, ValueError):
        attempt_window = 0
    try:
        ban_time = int(ban_time)
    except (TypeError, ValueError):
        ban_time = 0
    try:
        remember_seconds = int(remember_seconds)
    except (TypeError, ValueError):
        remember_seconds = 0

    if not 3 <= max_attempts <= 20:
        errors.append("FAIL2BAN_MAX_RETRY must be between 3 and 20.")
    if not max(max_attempts, 20) <= ip_max_attempts <= 10_000:
        errors.append(
            "FAIL2BAN_IP_MAX_RETRY must be at least 20, no smaller than the "
            "account threshold, and no greater than 10000."
        )
    if not 60 <= attempt_window <= 3_600:
        errors.append("FAIL2BAN_ATTEMPT_WINDOW must be between 60 and 3600 seconds.")
    if not 60 <= ban_time <= 86_400:
        errors.append("FAIL2BAN_BAN_TIME must be between 60 and 86400 seconds.")
    if not 3_600 <= remember_seconds <= 30 * 24 * 60 * 60:
        errors.append("LOGIN_REMEMBER_ME_SECONDS must be between 1 hour and 30 days.")
    if errors:
        raise ImproperlyConfigured(
            "Horilla login security configuration check failed:\n- "
            + "\n- ".join(errors)
        )


def validate_mfa_email_configuration(
    *,
    enabled,
    email_host,
    email_port,
    email_host_user,
    email_host_password,
    from_email,
    use_tls,
    use_ssl,
    fail_silently,
    timeout,
    otp_ttl,
    max_attempts,
    resend_cooldown,
    production=False,
):
    """Validate the fail-closed email MFA delivery boundary."""

    errors = []
    host = str(email_host or "").strip().lower()
    if production and not enabled:
        errors.append("TWO_FACTORS_AUTHENTICATION must be enabled in production.")
    if enabled and (
        not host
        or host in {"localhost", "127.0.0.1", "::1"}
        or host.endswith(".example.com")
        or host.endswith(".example.edu.cn")
    ):
        errors.append("EMAIL_HOST must name a real production SMTP server.")
    try:
        valid_port = 1 <= int(email_port) <= 65535
    except (TypeError, ValueError):
        valid_port = False
    if enabled and not valid_port:
        errors.append("EMAIL_PORT must be a valid TCP port.")
    if enabled and _is_placeholder(email_host_user):
        errors.append("EMAIL_HOST_USER must contain the production SMTP account.")
    if enabled and _is_placeholder(email_host_password):
        errors.append("EMAIL_HOST_PASSWORD must contain the production SMTP credential.")
    try:
        validate_email(str(from_email or ""))
    except Exception:
        if enabled:
            errors.append("DEFAULT_FROM_EMAIL must be a valid email address.")
    if enabled and bool(use_tls) == bool(use_ssl):
        errors.append("Exactly one of EMAIL_USE_TLS or EMAIL_USE_SSL must be enabled.")
    if enabled and fail_silently:
        errors.append("EMAIL_FAIL_SILENTLY must be False for production MFA.")
    try:
        valid_timeout = 1 <= int(timeout) <= 30
    except (TypeError, ValueError):
        valid_timeout = False
    if enabled and not valid_timeout:
        errors.append("EMAIL_TIMEOUT must be between 1 and 30 seconds.")
    try:
        valid_ttl = 60 <= int(otp_ttl) <= 600
    except (TypeError, ValueError):
        valid_ttl = False
    if enabled and not valid_ttl:
        errors.append("MFA_OTP_TTL_SECONDS must be between 60 and 600 seconds.")
    try:
        valid_attempts = 3 <= int(max_attempts) <= 10
    except (TypeError, ValueError):
        valid_attempts = False
    if enabled and not valid_attempts:
        errors.append("MFA_OTP_MAX_ATTEMPTS must be between 3 and 10.")
    try:
        valid_cooldown = 30 <= int(resend_cooldown) <= 300
    except (TypeError, ValueError):
        valid_cooldown = False
    if enabled and not valid_cooldown:
        errors.append(
            "MFA_OTP_RESEND_COOLDOWN_SECONDS must be between 30 and 300 seconds."
        )
    if errors:
        raise ImproperlyConfigured(
            "Horilla production MFA configuration check failed:\n- "
            + "\n- ".join(errors)
        )


def validate_field_encryption_configuration(raw_keys, *, production=False):
    """Require a valid, rotation-capable credential encryption keyring."""

    if not production:
        return
    raw = str(raw_keys or "").strip()
    errors = []
    if not raw:
        errors.append("FIELD_ENCRYPTION_KEYS is required in production.")
    seen = set()
    seen_material = set()
    for entry in filter(None, (item.strip() for item in raw.split(","))):
        key_id, separator, key_material = entry.partition(":")
        if (
            not separator
            or not key_id
            or len(key_id) > 32
            or not all(char.isalnum() or char in "_-" for char in key_id)
        ):
            errors.append(
                "FIELD_ENCRYPTION_KEYS entries must use key-id:fernet-key."
            )
            continue
        if key_id in seen:
            errors.append(f"FIELD_ENCRYPTION_KEYS repeats key id {key_id!r}.")
        seen.add(key_id)
        if key_material in seen_material:
            errors.append("FIELD_ENCRYPTION_KEYS must not reuse key material.")
        seen_material.add(key_material)
        try:
            decoded = base64.urlsafe_b64decode(key_material.encode("ascii"))
            if len(decoded) != 32:
                raise ValueError
        except (ValueError, UnicodeEncodeError):
            errors.append(
                f"FIELD_ENCRYPTION_KEYS key {key_id!r} must be a Fernet key."
            )
    if errors:
        raise ImproperlyConfigured(
            "Horilla database field encryption check failed:\n- "
            + "\n- ".join(errors)
        )


def validate_internal_service_credentials(credentials, required_callers):
    """Require strong, distinct credentials for mandatory in-process HR APIs."""

    configured = credentials if isinstance(credentials, dict) else {}
    required = {
        str(caller or "").strip().upper()
        for caller in (required_callers or ())
        if str(caller or "").strip()
    }
    errors = []
    tokens = []
    for caller in sorted(required):
        token = str(configured.get(caller, "") or "").strip()
        if _is_placeholder(token) or len(token.encode("utf-8")) < 32:
            errors.append(
                f"HR10 internal service credential for {caller} must contain "
                "at least 32 non-placeholder bytes."
            )
        else:
            tokens.append(token)
    if len(tokens) != len(set(tokens)):
        errors.append("HR10 internal service credentials must be distinct per caller.")
    if errors:
        raise ImproperlyConfigured(
            "Horilla internal service credential check failed:\n- "
            + "\n- ".join(errors)
        )


KNOWN_EXTERNAL_INTEGRATIONS = frozenset(
    {
        "HR16_IAM",
        "HR16_ASSET",
        "HR16_FINANCE",
        "HR08_IAM",
        "HR08_ACADEMIC",
        "HR15_PAYMENT",
        "HR18_SUBMISSION",
        "HR18_EXCHANGE",
    }
)


def validate_required_external_integrations(required, configured):
    """Fail production startup when a declared authority boundary is incomplete."""
    required_names = {
        str(name or "").strip().upper() for name in (required or ()) if str(name).strip()
    }
    errors = []
    unknown = required_names - KNOWN_EXTERNAL_INTEGRATIONS
    if unknown:
        errors.append(
            "REQUIRED_EXTERNAL_INTEGRATIONS contains unknown names: "
            + ", ".join(sorted(unknown))
        )
    hr08_pair = {"HR08_IAM", "HR08_ACADEMIC"}
    declared_hr08 = required_names & hr08_pair
    if declared_hr08 and declared_hr08 != hr08_pair:
        missing = sorted(hr08_pair - declared_hr08)
        errors.append(
            "HR08 external-teacher go-live requires IAM and academic "
            "integrations together; missing: " + ", ".join(missing)
        )

    for name in sorted(required_names & KNOWN_EXTERNAL_INTEGRATIONS):
        item = configured.get(name, {}) if isinstance(configured, dict) else {}
        endpoint = str(item.get("url", "") or "").strip()
        token = str(item.get("token", "") or "").strip()
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            errors.append(f"{name} requires a valid HTTPS provider URL.")
        if _is_placeholder(token) or len(token) < 16:
            errors.append(f"{name} requires a non-placeholder provider token.")
        try:
            timeout = float(item.get("timeout", 0))
        except (TypeError, ValueError):
            timeout = 0
        if not 1 <= timeout <= 60:
            errors.append(f"{name} timeout must be between 1 and 60 seconds.")

        if name in {"HR15_PAYMENT", "HR18_SUBMISSION"}:
            receipt_secret = str(item.get("receipt_secret", "") or "")
            receipt_key_id = str(item.get("receipt_key_id", "") or "").strip()
            if _is_placeholder(receipt_secret) or len(
                receipt_secret.encode("utf-8")
            ) < 32:
                errors.append(
                    f"{name} receipt HMAC secret must contain at least 32 "
                    "non-placeholder bytes."
                )
            if not receipt_key_id or len(receipt_key_id) > 128:
                errors.append(f"{name} receipt key id is invalid.")
        if name == "HR15_PAYMENT":
            provider_code = str(item.get("provider_code", "") or "").strip().upper()
            if (
                not provider_code
                or len(provider_code) > 64
                or any(
                    char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
                    for char in provider_code
                )
            ):
                errors.append("HR15_PAYMENT provider code is invalid.")

    if errors:
        raise ImproperlyConfigured(
            "Horilla required integration check failed:\n- " + "\n- ".join(errors)
        )


def apply_secure_defaults(env, debug: bool) -> dict:
    settings = {
        "SESSION_COOKIE_SECURE": True,
        "CSRF_COOKIE_SECURE": True,
        "SECURE_CONTENT_TYPE_NOSNIFF": True,
        "SECURE_REFERRER_POLICY": "strict-origin-when-cross-origin",
        "SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https"),
        # DEBUG=False is a production posture in this repository.  Do not let a
        # missing environment variable silently downgrade transport security;
        # operators who intentionally terminate without HTTPS must opt out
        # explicitly with SECURE_SSL_REDIRECT=0.
        "SECURE_SSL_REDIRECT": env.bool("SECURE_SSL_REDIRECT", default=True),
    }
    if settings["SECURE_SSL_REDIRECT"]:
        settings["SECURE_HSTS_SECONDS"] = env.int(
            "SECURE_HSTS_SECONDS", default=31536000
        )
        settings["SECURE_HSTS_INCLUDE_SUBDOMAINS"] = True
        settings["SECURE_HSTS_PRELOAD"] = True
    return settings
