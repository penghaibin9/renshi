"""
horilla/settings/__init__.py

跃科高校人事系统统一设置入口。

规则：
1. base 是上游基础设置；addons/local_settings 只能做受控覆盖。
2. HR Authority 必须在这里显式注册，不能依赖 AppConfig.ready() 修改根 URL。
3. HR13~HR18 并行施工时，只注册当前代码树真实存在的 Authority app；合流后自动形成完整有序注册表。
4. 开发、CI、迁移验收、生产统一 MySQL；非 MySQL 配置直接 fail-closed。
"""

import os
from importlib.util import find_spec

from django.core.exceptions import ImproperlyConfigured

from horilla.settings.runtime_seals import install_legacy_runtime_seals

from .base import *  # noqa: F401,F403

# Optional override modules are optional only when the module itself is absent.
# Never swallow an ImportError raised *inside* an existing override module: doing
# so can silently drop production secrets/security settings and boot with the
# base configuration instead of failing closed.
if find_spec(f"{__package__}.addons") is not None:
    from .addons import *  # noqa: F401,F403

if find_spec(f"{__package__}.local_settings") is not None:
    from .local_settings import *  # noqa: F401,F403

CORE_HR_APPS = [
    "hr_control_center",  # HR01
    "hr_structure",  # HR02
    "hr_staff",  # HR03
    "hr_recruitment",  # HR04
    "hr_onboarding",  # HR05
    "hr_changes",  # HR06
    "hr_contracts",  # HR07
    "hr_external",  # HR08
    "hr_qualification",  # HR09
    "hr10_development",  # HR10
    "hr_time",  # HR11
    "hr_assessment",  # HR12
]

PARALLEL_HR_APPS = [
    "hr_title",  # HR13
    "hr_appointment",  # HR14
    "hr_payroll",  # HR15
    "hr_exit",  # HR16
    "hr_self",  # HR17
    "hr_data",  # HR18
]

CANONICAL_HR_APPS = CORE_HR_APPS + [
    app for app in PARALLEL_HR_APPS if find_spec(app) is not None
]

for _app in CANONICAL_HR_APPS:
    if _app not in INSTALLED_APPS:  # noqa: F405
        INSTALLED_APPS.append(_app)  # noqa: F405

# Platform support access is global infrastructure, not an HR Authority.
if "platform_access" not in INSTALLED_APPS:  # noqa: F405
    INSTALLED_APPS.append("platform_access")  # noqa: F405

# HR04 public recruitment privacy notice.  The public page renders these
# server-owned values so every campaign uses the same reviewed notice version
# and retention policy instead of embedding unverifiable wording in JavaScript.
HR04_PRIVACY_NOTICE_VERSION = os.getenv(
    "HR04_PRIVACY_NOTICE_VERSION", "2026-01"
).strip()
HR04_CANDIDATE_RETENTION_DAYS = int(
    os.getenv("HR04_CANDIDATE_RETENTION_DAYS", "730")
)
HR04_PRIVACY_CONTACT = os.getenv(
    "HR04_PRIVACY_CONTACT", "招聘公告公布的联系方式"
).strip()
HR04_APPLICATION_MATERIAL_MAX_BYTES = int(
    os.getenv("HR04_APPLICATION_MATERIAL_MAX_BYTES", str(20 * 1024 * 1024))
)
if not 1 <= HR04_CANDIDATE_RETENTION_DAYS <= 36500:
    raise ImproperlyConfigured(
        "HR04_CANDIDATE_RETENTION_DAYS must be between 1 and 36500"
    )
if not 1 <= HR04_APPLICATION_MATERIAL_MAX_BYTES <= MALWARE_SCAN_MAX_BYTES:  # noqa: F405
    raise ImproperlyConfigured(
        "HR04_APPLICATION_MATERIAL_MAX_BYTES must be positive and not exceed MALWARE_SCAN_MAX_BYTES"
    )

# HR09 and HR11 consume HR10-owned evidence/time windows through authenticated
# internal HTTP contracts.  These credentials are intentionally separate so a
# compromised consumer cannot impersonate another HR domain.
HR10_INTERNAL_SERVICE_CREDENTIALS = {
    "HR09": os.getenv("HR10_HR09_SERVICE_TOKEN", "").strip(),
    "HR11": os.getenv("HR10_HR11_SERVICE_TOKEN", "").strip(),
}

# HR15 freezes payroll inputs only through source-owned read contracts.  The
# bundled deployment uses the canonical HR03/HR11/HR12/HR14 adapters; missing
# upstream facts still fail closed inside each adapter.
HR15_PAYROLL_INPUT_PROVIDERS = {
    "HR03": "hr_payroll.services.input_fact_providers.Hr03PayrollInputProvider",
    "HR11": "hr_payroll.services.input_fact_providers.Hr11PayrollInputProvider",
    "HR12": "hr_payroll.services.input_fact_providers.Hr12PayrollInputProvider",
    "HR14": "hr_payroll.services.input_fact_providers.Hr14PayrollInputProvider",
}

# Production finance gateway. The adapter never fabricates a successful bank
# response: dispatch is HTTPS-bound and terminal receipts require an HMAC seal.
HR15_PAYMENT_HTTP_ENDPOINT = os.getenv("HR15_PAYMENT_HTTP_ENDPOINT", "").strip()
HR15_PAYMENT_HTTP_TOKEN = os.getenv("HR15_PAYMENT_HTTP_TOKEN", "").strip()
HR15_PAYMENT_HTTP_TIMEOUT_SECONDS = os.getenv(
    "HR15_PAYMENT_HTTP_TIMEOUT_SECONDS", "15"
)
HR15_PAYMENT_RECEIPT_HMAC_SECRET = os.getenv(
    "HR15_PAYMENT_RECEIPT_HMAC_SECRET", ""
).strip()
HR15_PAYMENT_RECEIPT_KEY_ID = os.getenv(
    "HR15_PAYMENT_RECEIPT_KEY_ID", ""
).strip()
HR15_PAYMENT_PROVIDER_CODE = os.getenv(
    "HR15_PAYMENT_PROVIDER_CODE", ""
).strip().upper()
HR15_PAYMENT_PROVIDERS = (
    {
        HR15_PAYMENT_PROVIDER_CODE:
            "hr_payroll.providers.payment_http.HttpsPaymentProvider"
    }
    if HR15_PAYMENT_HTTP_ENDPOINT and HR15_PAYMENT_PROVIDER_CODE
    else {}
)

# HR18 external delivery is enabled only when deployment credentials are
# explicitly present.  Queueing remains fail-closed without them; no local
# adapter can turn a formal submission or exchange into a fabricated success.
HR18_SUBMISSION_HTTP_ENDPOINT = os.getenv(
    "HR18_SUBMISSION_HTTP_ENDPOINT", ""
).strip()
HR18_SUBMISSION_HTTP_TOKEN = os.getenv("HR18_SUBMISSION_HTTP_TOKEN", "").strip()
HR18_SUBMISSION_HTTP_TIMEOUT_SECONDS = os.getenv(
    "HR18_SUBMISSION_HTTP_TIMEOUT_SECONDS", "15"
)
HR18_SUBMISSION_HTTP_PROVIDER_VERSION = os.getenv(
    "HR18_SUBMISSION_HTTP_PROVIDER_VERSION", "https-v1"
).strip()
HR18_SUBMISSION_RECEIPT_HMAC_SECRET = os.getenv(
    "HR18_SUBMISSION_RECEIPT_HMAC_SECRET", ""
).strip()
HR18_SUBMISSION_RECEIPT_KEY_ID = os.getenv(
    "HR18_SUBMISSION_RECEIPT_KEY_ID", ""
).strip()
HR18_SUBMISSION_DISPATCH_PROVIDER_KEY = os.getenv(
    "HR18_SUBMISSION_DISPATCH_PROVIDER_KEY", "EDU_PLATFORM"
).strip()
HR18_SUBMISSION_DISPATCH_PROVIDER = (
    "hr_data.providers.submission_http.HttpsSubmissionAdapter"
    if HR18_SUBMISSION_HTTP_ENDPOINT
    else ""
)

HR18_EXCHANGE_HTTP_ENDPOINT = os.getenv("HR18_EXCHANGE_HTTP_ENDPOINT", "").strip()
HR18_EXCHANGE_HTTP_TOKEN = os.getenv("HR18_EXCHANGE_HTTP_TOKEN", "").strip()
HR18_EXCHANGE_HTTP_TIMEOUT_SECONDS = os.getenv(
    "HR18_EXCHANGE_HTTP_TIMEOUT_SECONDS", "15"
)
HR18_EXCHANGE_HTTP_PROVIDER_VERSION = os.getenv(
    "HR18_EXCHANGE_HTTP_PROVIDER_VERSION", "https-v1"
).strip()
HR18_EXCHANGE_HTTP_PROVIDER_KEY = os.getenv(
    "HR18_EXCHANGE_HTTP_PROVIDER_KEY", "EDU_PLATFORM"
).strip().upper()
HR18_EXCHANGE_PROVIDERS = (
    {
        HR18_EXCHANGE_HTTP_PROVIDER_KEY:
            "hr_data.providers.exchange_http.https_exchange_provider"
    }
    if HR18_EXCHANGE_HTTP_ENDPOINT and HR18_EXCHANGE_HTTP_PROVIDER_KEY
    else {}
)

# Institutions differ in which upstream authority systems they operate. The
# deployment must explicitly name every boundary that is required for its
# go-live scope; declared integrations then become a fail-closed startup gate.
REQUIRED_EXTERNAL_INTEGRATIONS = {
    item.strip().upper()
    for item in os.getenv("REQUIRED_EXTERNAL_INTEGRATIONS", "").split(",")
    if item.strip()
}

if IS_PRODUCTION:  # noqa: F405
    from horilla.settings.security import (
        validate_hr04_privacy_configuration,
        validate_internal_service_credentials,
        validate_required_external_integrations,
    )

    validate_hr04_privacy_configuration(
        notice_version=HR04_PRIVACY_NOTICE_VERSION,
        retention_days=HR04_CANDIDATE_RETENTION_DAYS,
        privacy_contact=HR04_PRIVACY_CONTACT,
        material_max_bytes=HR04_APPLICATION_MATERIAL_MAX_BYTES,
        scan_max_bytes=MALWARE_SCAN_MAX_BYTES,  # noqa: F405
    )

    validate_internal_service_credentials(
        HR10_INTERNAL_SERVICE_CREDENTIALS,
        required_callers=("HR09", "HR11"),
    )

    validate_required_external_integrations(
        REQUIRED_EXTERNAL_INTEGRATIONS,
        {
            "HR08_IAM": {
                "url": HR08_IAM_PROVIDER["BASE_URL"],  # noqa: F405
                "token": HR08_IAM_PROVIDER["TOKEN"],  # noqa: F405
                "timeout": HR08_IAM_PROVIDER["TIMEOUT_MS"] / 1000,  # noqa: F405
            },
            "HR08_ACADEMIC": {
                "url": HR08_ACADEMIC_PROVIDER["BASE_URL"],  # noqa: F405
                "token": HR08_ACADEMIC_PROVIDER["TOKEN"],  # noqa: F405
                "timeout": HR08_ACADEMIC_PROVIDER["TIMEOUT_MS"] / 1000,  # noqa: F405
            },
            "HR15_PAYMENT": {
                "url": HR15_PAYMENT_HTTP_ENDPOINT,
                "token": HR15_PAYMENT_HTTP_TOKEN,
                "timeout": HR15_PAYMENT_HTTP_TIMEOUT_SECONDS,
                "receipt_secret": HR15_PAYMENT_RECEIPT_HMAC_SECRET,
                "receipt_key_id": HR15_PAYMENT_RECEIPT_KEY_ID,
                "provider_code": HR15_PAYMENT_PROVIDER_CODE,
            },
            "HR16_IAM": {
                "url": HR16_EXIT_EXTERNAL_PROVIDERS["IAM"]["url"],  # noqa: F405
                "token": HR16_EXIT_EXTERNAL_PROVIDERS["IAM"]["token"],  # noqa: F405
                "timeout": HR16_EXIT_EXTERNAL_PROVIDERS["IAM"]["timeoutSeconds"],  # noqa: F405
            },
            "HR16_ASSET": {
                "url": HR16_EXIT_EXTERNAL_PROVIDERS["ASSET"]["url"],  # noqa: F405
                "token": HR16_EXIT_EXTERNAL_PROVIDERS["ASSET"]["token"],  # noqa: F405
                "timeout": HR16_EXIT_EXTERNAL_PROVIDERS["ASSET"]["timeoutSeconds"],  # noqa: F405
            },
            "HR16_FINANCE": {
                "url": HR16_EXIT_EXTERNAL_PROVIDERS["FINANCE"]["url"],  # noqa: F405
                "token": HR16_EXIT_EXTERNAL_PROVIDERS["FINANCE"]["token"],  # noqa: F405
                "timeout": HR16_EXIT_EXTERNAL_PROVIDERS["FINANCE"]["timeoutSeconds"],  # noqa: F405
            },
            "HR18_SUBMISSION": {
                "url": HR18_SUBMISSION_HTTP_ENDPOINT,
                "token": HR18_SUBMISSION_HTTP_TOKEN,
                "timeout": HR18_SUBMISSION_HTTP_TIMEOUT_SECONDS,
                "receipt_secret": HR18_SUBMISSION_RECEIPT_HMAC_SECRET,
                "receipt_key_id": HR18_SUBMISSION_RECEIPT_KEY_ID,
            },
            "HR18_EXCHANGE": {
                "url": HR18_EXCHANGE_HTTP_ENDPOINT,
                "token": HR18_EXCHANGE_HTTP_TOKEN,
                "timeout": HR18_EXCHANGE_HTTP_TIMEOUT_SECONDS,
            },
        },
    )

# Replace the legacy company middleware with a compatibility subclass that
# supports platform-only superusers, then require audited tenant elevation
# immediately after tenant resolution.
_company_middleware = "base.middleware.CompanyMiddleware"
_safe_company_middleware = "platform_access.middleware.SafeCompanyMiddleware"
_elevation_middleware = "platform_access.middleware.PlatformTenantElevationMiddleware"
if _company_middleware in MIDDLEWARE:  # noqa: F405
    _company_index = MIDDLEWARE.index(_company_middleware)  # noqa: F405
    MIDDLEWARE[_company_index] = _safe_company_middleware  # noqa: F405
else:
    _company_index = MIDDLEWARE.index(_safe_company_middleware)  # noqa: F405
if _elevation_middleware not in MIDDLEWARE:  # noqa: F405
    MIDDLEWARE.insert(_company_index + 1, _elevation_middleware)  # noqa: F405

PLATFORM_TENANT_ELEVATION_MAX_MINUTES = int(
    os.getenv("PLATFORM_TENANT_ELEVATION_MAX_MINUTES", "60")
)

# Install the final retired-Authority write seal after deployment/platform
# middleware overrides, so neither local settings nor platform elevation wiring
# can accidentally remove it.
install_legacy_runtime_seals(globals())

# PATCH-00 / takeover contract: MySQL is the one signing database for dev,
# CI, migrations and production. Failing here is intentional.
_db = DATABASES.get("default", {})  # noqa: F405
_engine = _db.get("ENGINE", "")
if _engine != "django.db.backends.mysql":
    raise ImproperlyConfigured(
        "renshi database contract requires MySQL. "
        f"Configured ENGINE={_engine or '<empty>'}. "
        "Set DATABASE_URL=mysql://... or DB_ENGINE=django.db.backends.mysql."
    )

_mysql_options = _db.setdefault("OPTIONS", {})
_mysql_options.setdefault("charset", "utf8mb4")
_mysql_options.setdefault(
    "init_command",
    "SET sql_mode='STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO'",
)
_mysql_options.setdefault("isolation_level", "read committed")
_db.setdefault("CONN_MAX_AGE", int(os.getenv("DB_CONN_MAX_AGE", "60")))
_db.setdefault("CONN_HEALTH_CHECKS", True)
