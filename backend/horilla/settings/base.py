"""
base.py — Main Django settings for Horilla
"""

import os
from datetime import timedelta
from os.path import join
from pathlib import Path

import environ
from django.contrib.messages import constants as messages
from django.core.files.storage import FileSystemStorage

# ========================================
# BASE PATH & ENVIRONMENT CONFIGURATION
# ========================================
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
RUNTIME_DIR = REPO_ROOT / ".runtime"

# Keep BASE_DIR as the backend root so existing app-local paths remain valid.
BASE_DIR = BACKEND_DIR

env = environ.Env(
    DEBUG=(bool, True),
    SECRET_KEY=(str, "django-insecure-default-key"),
    ALLOWED_HOSTS=(list, ["*"]),
    CSRF_TRUSTED_ORIGINS=(list, ["http://localhost:8000"]),
    SECURE_SSL_REDIRECT=(bool, False),
)

# Existing process environment (Compose, systemd, CI) wins over .env values.
env.read_env(os.path.join(REPO_ROOT, ".env"), overwrite=False)

# ========================================
# CORE DJANGO SETTINGS
# ========================================
SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
HORILLA_ENV = env("HORILLA_ENV", default="")
REDIS_URL = env("REDIS_URL", default=None)
REDIS_PASSWORD = env("REDIS_PASSWORD", default="")
FAIL2BAN_MAX_RETRY = env.int("FAIL2BAN_MAX_RETRY", default=5)
FAIL2BAN_IP_MAX_RETRY = env.int("FAIL2BAN_IP_MAX_RETRY", default=100)
FAIL2BAN_ATTEMPT_WINDOW = env.int("FAIL2BAN_ATTEMPT_WINDOW", default=900)
FAIL2BAN_BAN_TIME = env.int("FAIL2BAN_BAN_TIME", default=900)
FAIL2BAN_TRUST_X_REAL_IP = env.bool("FAIL2BAN_TRUST_X_REAL_IP", default=False)
TWO_FACTORS_AUTHENTICATION = env.bool(
    "TWO_FACTORS_AUTHENTICATION", default=False
)
MFA_OTP_TTL_SECONDS = env.int("MFA_OTP_TTL_SECONDS", default=300)
MFA_OTP_MAX_ATTEMPTS = env.int("MFA_OTP_MAX_ATTEMPTS", default=5)
MFA_OTP_RESEND_COOLDOWN_SECONDS = env.int(
    "MFA_OTP_RESEND_COOLDOWN_SECONDS", default=60
)
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
EMAIL_FAIL_SILENTLY = env.bool("EMAIL_FAIL_SILENTLY", default=False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@localhost")
FIELD_ENCRYPTION_KEYS = env("FIELD_ENCRYPTION_KEYS", default="")
MALWARE_SCAN_REQUIRED = env.bool("MALWARE_SCAN_REQUIRED", default=False)
MALWARE_SCAN_HOST = env("MALWARE_SCAN_HOST", default="")
MALWARE_SCAN_PORT = env.int("MALWARE_SCAN_PORT", default=3310)
MALWARE_SCAN_TIMEOUT_SECONDS = env.float(
    "MALWARE_SCAN_TIMEOUT_SECONDS", default=10.0
)
MALWARE_SCAN_MAX_BYTES = env.int(
    "MALWARE_SCAN_MAX_BYTES", default=50 * 1024 * 1024
)

THEME_APP = "horilla_theme"

INSTALLED_APPS = [
    # Default Django apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    # Third-party apps
    "notifications",
    "mathfilters",
    "corsheaders",
    "simple_history",
    "django_filters",
    "widget_tweaks",
    "auditlog",
    "django_apscheduler",
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_yasg",
    # Core Horilla apps
    "horilla_auth",
    THEME_APP,
    "base",
    "employee",
    "recruitment",
    "leave",
    "pms",
    "onboarding",
    "asset",
    "attendance",
    "payroll",
    "accessibility",
    "horilla_audit",
    "horilla_widgets",
    "horilla_crumbs",
    "horilla_documents",
    "horilla_views",
    "horilla_automations",
    "horilla_api",
    "biometric",
    "helpdesk",
    "offboarding",
    "horilla_backup",
    "project",
    "horilla_meet",
    "report",
    "whatsapp",
    "horilla_ldap",
    "horilla_dbtemplate",
    "horilla_tour",
    "hr_control_center",
    "hr_structure",
    "hr_staff",
    "hr_time",
    "hr_recruitment",
    "hr_external",
    "hr_onboarding",
    "hr_contracts",
    "hr_changes",
]

# ========================================
# REST FRAMEWORK CONFIGURATION
# ========================================

REST_FRAMEWORK = {
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "PAGE_SIZE": 20,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
}

SWAGGER_SETTINGS = {
    "SECURITY_DEFINITIONS": {
        "Bearer": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": "Enter your Bearer token here",
        },
        "Basic": {"type": "basic", "description": "Basic authentication."},
    },
    "SECURITY": [{"Bearer": []}, {"Basic": []}],
}

APSCHEDULER_DATETIME_FORMAT = "N j, Y, f:s a"

APSCHEDULER_RUN_NOW_TIMEOUT = 25  # Seconds

# ========================================
# MIDDLEWARE
# ========================================
MIDDLEWARE = [
    "base.observability.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "base.upload_security.MalwareScanMiddleware",
    "base.runtime_automations.RuntimeAutomationMiddleware",
    "base.signals.Fail2BanMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Horilla-specific middlewares
    "base.middleware.CompanyMiddleware",
    "base.middleware.ForcePasswordChangeMiddleware",
    "base.middleware.TwoFactorAuthMiddleware",
    "accessibility.middlewares.AccessibilityMiddleware",
    "horilla.horilla_middlewares.MethodNotAllowedMiddleware",
    "horilla.horilla_middlewares.SVGSecurityMiddleware",
    "horilla.horilla_middlewares.MissingParameterMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
]

ROOT_URLCONF = "horilla.urls"

# ========================================
# DATABASE CONFIGURATION
# ========================================
if env("DATABASE_URL", default=None):
    DATABASES = {"default": env.db()}
else:
    _database_engine = env("DB_ENGINE", default="django.db.backends.sqlite3")
    # Backend options are not interchangeable.  In particular, sqlite's
    # ``timeout`` is forwarded as a keyword argument by the MySQL backend and
    # makes every management command fail before it can run a system check.
    _database_options = (
        {"timeout": 30}
        if _database_engine == "django.db.backends.sqlite3"
        else {}
    )
    _default_database_path = RUNTIME_DIR / "db" / "TestDB.sqlite3"
    if _database_engine == "django.db.backends.sqlite3":
        _default_database_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": _database_engine,
            "NAME": env("DB_NAME", default=str(_default_database_path)),
            "USER": env("DB_USER", default=""),
            "PASSWORD": env("DB_PASSWORD", default=""),
            "HOST": env("DB_HOST", default=""),
            "PORT": env("DB_PORT", default=""),
            "OPTIONS": _database_options,
        }
    }

# MySQL cannot materialize Django partial unique indexes. Every conditional
# constraint currently used by the product has a generated-column unique-index
# migration and is audited by base.production_checks. Suppress Django's generic
# warning only after replacing the three constraints that did not have a
# physical MySQL equivalent. SAMEORIGIN is intentional because authenticated
# document/PDF previews are rendered in same-origin iframes.
if DATABASES.get("default", {}).get("ENGINE") == "django.db.backends.mysql":
    SILENCED_SYSTEM_CHECKS = ["models.W036", "security.W019"]

# HR08 external workforce providers. Writes remain queued until a deployment
# supplies the real IAM or academic authority boundary.
HR08_IAM_PROVIDER = {
    "BASE_URL": env("HR08_IAM_PROVIDER_URL", default=""),
    "TOKEN": env("HR08_IAM_PROVIDER_TOKEN", default=""),
    "TIMEOUT_MS": env.int("HR08_IAM_PROVIDER_TIMEOUT_MS", default=10000),
}
HR08_ACADEMIC_PROVIDER = {
    "BASE_URL": env("HR08_ACADEMIC_PROVIDER_URL", default=""),
    "TOKEN": env("HR08_ACADEMIC_PROVIDER_TOKEN", default=""),
    "TIMEOUT_MS": env.int("HR08_ACADEMIC_PROVIDER_TIMEOUT_MS", default=10000),
}

# HR16 external effect providers. Empty URL/token pairs intentionally fail
# closed as UNAVAILABLE until deployment supplies real authority endpoints.
HR16_EXIT_EXTERNAL_PROVIDERS = {
    "IAM": {
        "url": env("HR16_IAM_PROVIDER_URL", default=""),
        "token": env("HR16_IAM_PROVIDER_TOKEN", default=""),
        "timeoutSeconds": env.int("HR16_IAM_PROVIDER_TIMEOUT", default=10),
    },
    "ASSET": {
        "url": env("HR16_ASSET_PROVIDER_URL", default=""),
        "token": env("HR16_ASSET_PROVIDER_TOKEN", default=""),
        "timeoutSeconds": env.int("HR16_ASSET_PROVIDER_TIMEOUT", default=10),
    },
    "FINANCE": {
        "url": env("HR16_FINANCE_PROVIDER_URL", default=""),
        "token": env("HR16_FINANCE_PROVIDER_TOKEN", default=""),
        "timeoutSeconds": env.int("HR16_FINANCE_PROVIDER_TIMEOUT", default=10),
    },
}

# SQLite: enable WAL so reads (list/search) don't block session writes from
# concurrent requests like notification polling.
from django.db.backends.signals import connection_created


def _configure_sqlite_connection(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=30000;")


connection_created.connect(_configure_sqlite_connection)

# ========================================
# CACHE (optional Redis when REDIS_URL is set)
# ========================================
# Fresh clones / runserver keep Django's default LocMem cache.
# Docker Compose sets REDIS_URL so the Redis service is actually used
# (requires django-redis in requirements.txt).
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
            "KEY_PREFIX": "horilla",
        }
    }

# ========================================
# STATIC & MEDIA FILES
# ========================================
STATIC_URL = "static/"
STATIC_ROOT = RUNTIME_DIR / "staticfiles"
STATICFILES_DIRS = [FRONTEND_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = RUNTIME_DIR / "media"

PRODUCTION_BACKUP_ROOT = env(
    "PRODUCTION_BACKUP_ROOT", default=str(RUNTIME_DIR / "backups")
)
PRODUCTION_BACKUP_ENCRYPTION_KEY = env(
    "PRODUCTION_BACKUP_ENCRYPTION_KEY", default=""
)
PRODUCTION_BACKUP_RETENTION_COUNT = env.int(
    "PRODUCTION_BACKUP_RETENTION_COUNT", default=30
)
PRODUCTION_BACKUP_INTERVAL_HOURS = env.int(
    "PRODUCTION_BACKUP_INTERVAL_HOURS", default=24
)
CANONICAL_HR_JOB_BATCH_SIZE = env.int("CANONICAL_HR_JOB_BATCH_SIZE", default=2000)
if not 1 <= CANONICAL_HR_JOB_BATCH_SIZE <= 5000:
    raise ValueError("CANONICAL_HR_JOB_BATCH_SIZE must be between 1 and 5000")

# ========================================
# AUTHENTICATION & SECURITY
# ========================================
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "horilla_auth.HorillaUser"

X_FRAME_OPTIONS = "SAMEORIGIN"

# ========================================
# TEMPLATES
# ========================================
# In production (DEBUG=False) these are wrapped in the cached template
# loader so Django compiles each template once per process instead of
# re-parsing it (and re-running horilla_dbtemplate's DB-lookup chain) on
# every include, on every request. Left uncached in DEBUG so template
# edits during development are picked up without restarting the server.
_TEMPLATE_LOADERS = [
    "horilla_dbtemplate.loaders.Loader",
    ("django.template.loaders.filesystem.Loader", [BASE_DIR / THEME_APP / "templates"]),
    "django.template.loaders.app_directories.Loader",
    ("django.template.loaders.filesystem.Loader", [FRONTEND_DIR / "templates"]),
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [FRONTEND_DIR / "templates"],
        "APP_DIRS": False,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # Horilla dynamic context processors
                "horilla.config.get_MENUS",
                "base.context_processors.get_companies",
                "base.context_processors.white_labelling_company",
                "base.context_processors.doc_base_url",
                "base.context_processors.resignation_request_enabled",
                "base.context_processors.timerunner_enabled",
                "base.context_processors.intial_notice_period",
                "base.context_processors.check_candidate_self_tracking",
                "base.context_processors.check_candidate_self_tracking_rating",
                "base.context_processors.get_initial_prefix",
                "base.context_processors.biometric_app_exists",
                "base.context_processors.enable_late_come_early_out_tracking",
                "base.context_processors.enable_profile_edit",
                "base.context_processors.export_access_enabled",
                "base.context_processors.navbar_languages",
                "horilla_tour.context_processors.pending_tours_flag",
                "horilla_crumbs.context_processors.breadcrumbs",
            ],
            "loaders": (
                _TEMPLATE_LOADERS
                if DEBUG
                else [("django.template.loaders.cached.Loader", _TEMPLATE_LOADERS)]
            ),
        },
    },
]

WSGI_APPLICATION = "horilla.wsgi.application"

# ========================================
# INTERNATIONALIZATION
# ========================================
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = env("TIME_ZONE", default="Asia/Shanghai")
USE_I18N = True
USE_TZ = True

LANGUAGES = (
    ("en", "English (US)"),
    ("de", "Deutsch"),
    ("es", "Español"),
    ("fr", "Français"),
    ("ar", "العربية"),
    ("pt-br", "Português (Brasil)"),
    ("zh-hans", "简体中文"),
    ("zh-hant", "繁體中文"),
    ("it", "Italian"),
    ("tr", "Turkish"),
    ("uk", "Українська"),
)

LOCALE_PATHS = [join(BASE_DIR, "horilla", "locale")]

# ========================================
# LOGGING, MESSAGES, OTHER GLOBALS
# ========================================
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MESSAGE_TAGS = {
    messages.DEBUG: "oh-alert--warning",
    messages.INFO: "oh-alert--info",
    messages.SUCCESS: "oh-alert--success",
    messages.WARNING: "oh-alert--warning",
    messages.ERROR: "oh-alert--danger",
}

LOGIN_URL = "/login"
LOGIN_REMEMBER_ME_SECONDS = env.int("LOGIN_REMEMBER_ME_SECONDS", default=14 * 24 * 60 * 60)
SIMPLE_HISTORY_REVERT_DISABLED = True

DJANGO_NOTIFICATIONS_CONFIG = {
    "USE_JSONFIELD": True,
    "SOFT_DELETE": True,
    "USE_WATCHED": True,
    "NOTIFICATIONS_STORAGE": "notifications.storage.DatabaseStorage",
    "TEMPLATE": "notifications.html",
}

# ========================================
# HORILLA-SPECIFIC SETTINGS
# ========================================
WHITE_LABELLING = False
NESTED_SUBORDINATE_VISIBILITY = False
SIDEBARS = [
    "employee",
    "attendance",
    "leave",
    "payroll",
    "recruitment",
    "onboarding",
    "offboarding",
    "pms",
    "project",
    "asset",
    "helpdesk",
    "report",
]

# Audit logging is opt-in: the horilla_audit app registers models explicitly
# through its registry, driven by AuditModelConfig and a default whitelist
# (Employee, EmployeeWorkInformation, EmployeeBankDetails).
AUDITLOG_INCLUDE_ALL_MODELS = False
AUDITLOG_EXCLUDE_TRACKING_MODELS = (
    # "<app_name>",
    # "<app_name>.<model>"
)

EMAIL_BACKEND = "base.backends.ConfiguredEmailBackend"

"""
DB_INIT_PASSWORD: str

The password used for database setup and initialization. This password is a
48-character alphanumeric string generated using a UUID to ensure high entropy and security.
"""
DB_INIT_PASSWORD = env(
    "DB_INIT_PASSWORD", default="d3f6a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d"
)

# ========================================
# PERMISSIONS / CUSTOM LOGIC
# ========================================
# When True, group permissions are scoped per company via
# base.models.CompanyGroupAssignment (resolved by CompanyScopedBackend).
# When False, legacy behavior: user.groups grant permissions globally.
# Instant rollback switch: set the COMPANY_SCOPED_PERMISSIONS env var to False.
COMPANY_SCOPED_PERMISSIONS = env.bool("COMPANY_SCOPED_PERMISSIONS", default=True)

NO_PERMISSION_MODALS = [
    "companygroupassignment",
    "historicalbonuspoint",
    "assetreport",
    "assetdocuments",
    "returnimages",
    "holiday",
    "companyleave",
    "historicalavailableleave",
    "historicalleaverequest",
    "historicalleaveallocationrequest",
    "leaverequestconditionapproval",
    "historicalcompensatoryleaverequest",
    "employeepastleaverestrict",
    "overrideleaverequests",
    "historicalrotatingworktypeassign",
    "employeeshiftday",
    "historicalrotatingshiftassign",
    "historicalworktyperequest",
    "historicalshiftrequest",
    "multipleapprovalmanagers",
    "attachment",
    "announcementview",
    "emaillog",
    "driverviewed",
    "dashboardemployeecharts",
    "attendanceallowedip",
    "tracklatecomeearlyout",
    "historicalcontract",
    "overrideattendance",
    "overrideleaverequest",
    "overrideworkinfo",
    "multiplecondition",
    "historicalpayslip",
    "reimbursementmultipleattachment",
    "workrecord",
    "historicalticket",
    "skill",
    "historicalcandidate",
    "rejectreason",
    "historicalrejectedcandidate",
    "rejectedcandidate",
    "stagefiles",
    "stagenote",
    "questionordering",
    "recruitmentsurveyordering",
    "recruitmentsurveyanswer",
    "recruitmentgeneralsetting",
    "resume",
    "recruitmentmailtemplate",
    "profileeditfeature",
]

FILE_STORAGE = FileSystemStorage(location="csv_tmp/")

HORILLA_DATE_FORMATS = {
    "DD/MM/YY": "%d/%m/%y",
    "DD-MM-YYYY": "%d-%m-%Y",
    "DD.MM.YYYY": "%d.%m.%Y",
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
    "YYYY/MM/DD": "%Y/%m/%d",
    "MMMM D, YYYY": "%B %d, %Y",
    "DD MMMM, YYYY": "%d %B, %Y",
    "MMM. D, YYYY": "%b. %d, %Y",
    "D MMM. YYYY": "%d %b. %Y",
    "dddd, MMMM D, YYYY": "%A, %B %d, %Y",
}

HORILLA_TIME_FORMATS = {
    "hh:mm A": "%I:%M %p",  # 12-hour format
    "HH:mm": "%H:%M",  # 24-hour format
    "HH:mm:ss.SSSSSS": "%H:%M:%S.%f",  # 24-hour format with seconds and microseconds
}

BIO_DEVICE_THREADS = {}

DYNAMIC_URL_PATTERNS = []

APP_URLS = [
    "base.urls",
    "employee.urls",
]

APPS = [
    "auth",
    "base",
    "employee",
    "horilla_documents",
    "horilla_automations",
]

# ========================================
# LDAP CONFIGURATION (Default)
# ========================================
AUTH_LDAP_SERVER_URI = env("AUTH_LDAP_SERVER_URI", default="ldap://127.0.0.1:389")
AUTH_LDAP_BIND_DN = env("AUTH_LDAP_BIND_DN", default="cn=admin,dc=horilla,dc=com")
AUTH_LDAP_BIND_PASSWORD = env("AUTH_LDAP_BIND_PASSWORD", default="")

AUTH_LDAP_USER_ATTR_MAP = {
    "first_name": "givenName",
    "last_name": "sn",
    "email": "mail",
}

# Default LDAP settings
DEFAULT_LDAP_CONFIG = {
    "LDAP_SERVER": env("LDAP_SERVER", default="ldap://127.0.0.1:389"),
    "BIND_DN": env("BIND_DN", default="cn=admin,dc=horilla,dc=com"),
    "BIND_PASSWORD": env("BIND_PASSWORD", default=""),
    "BASE_DN": env("BASE_DN", default="ou=users,dc=horilla,dc=com"),
}

# CompanyScopedBackend subclasses ModelBackend; it behaves identically while
# COMPANY_SCOPED_PERMISSIONS is False. It must REPLACE ModelBackend (Django
# unions grants across backends, so listing both would keep global perms).
AUTHENTICATION_BACKENDS = [
    "base.auth_backends.CompanyScopedBackend",
    # "django_auth_ldap.backend.LDAPBackend",
]

AUTH_LDAP_ALWAYS_UPDATE_USER = True

# ========================================
# PRODUCTION SECURITY GATES
# ========================================
# Fail closed when DEBUG=False or HORILLA_ENV=production. Local DEBUG=True
# tutorials keep insecure-but-documented defaults for open-source onboarding.
from horilla.settings.security import (  # noqa: E402
    apply_secure_defaults,
    is_production_mode,
    validate_login_security_configuration,
    validate_malware_scanner_configuration,
    validate_field_encryption_configuration,
    validate_mfa_email_configuration,
    validate_production_secrets,
)

IS_PRODUCTION = is_production_mode(DEBUG, HORILLA_ENV)

if IS_PRODUCTION:
    validate_login_security_configuration(
        max_attempts=FAIL2BAN_MAX_RETRY,
        ip_max_attempts=FAIL2BAN_IP_MAX_RETRY,
        attempt_window=FAIL2BAN_ATTEMPT_WINDOW,
        ban_time=FAIL2BAN_BAN_TIME,
        remember_seconds=LOGIN_REMEMBER_ME_SECONDS,
    )
    validate_field_encryption_configuration(
        FIELD_ENCRYPTION_KEYS,
        production=True,
    )
    validate_mfa_email_configuration(
        enabled=TWO_FACTORS_AUTHENTICATION,
        email_host=EMAIL_HOST,
        email_port=EMAIL_PORT,
        email_host_user=EMAIL_HOST_USER,
        email_host_password=EMAIL_HOST_PASSWORD,
        from_email=DEFAULT_FROM_EMAIL,
        use_tls=EMAIL_USE_TLS,
        use_ssl=EMAIL_USE_SSL,
        fail_silently=EMAIL_FAIL_SILENTLY,
        timeout=EMAIL_TIMEOUT,
        otp_ttl=MFA_OTP_TTL_SECONDS,
        max_attempts=MFA_OTP_MAX_ATTEMPTS,
        resend_cooldown=MFA_OTP_RESEND_COOLDOWN_SECONDS,
        production=True,
    )
    validate_malware_scanner_configuration(
        required=MALWARE_SCAN_REQUIRED,
        host=MALWARE_SCAN_HOST,
        port=MALWARE_SCAN_PORT,
        timeout_seconds=MALWARE_SCAN_TIMEOUT_SECONDS,
        max_bytes=MALWARE_SCAN_MAX_BYTES,
        production=True,
    )
    validate_production_secrets(
        SECRET_KEY,
        ALLOWED_HOSTS,
        DB_INIT_PASSWORD,
        csrf_trusted_origins=CSRF_TRUSTED_ORIGINS,
        database_password=DATABASES["default"].get("PASSWORD", ""),
        redis_url=REDIS_URL,
        redis_password=REDIS_PASSWORD,
        backup_encryption_key=PRODUCTION_BACKUP_ENCRYPTION_KEY,
    )

if not DEBUG:
    globals().update(apply_secure_defaults(env, DEBUG))

# Container-native logs: stdout/stderr only, one record per line, with a
# request correlation id and redaction of common credential shapes.
LOG_LEVEL = env("LOG_LEVEL", default="INFO").upper()
LOG_FORMAT = env("LOG_FORMAT", default="json" if IS_PRODUCTION else "console").lower()
_selected_formatter = "json" if LOG_FORMAT == "json" else "console"
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_context": {"()": "base.observability.RequestContextFilter"},
    },
    "formatters": {
        "json": {"()": "base.observability.JsonFormatter"},
        "console": {
            "format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_context"],
            "formatter": _selected_formatter,
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
