"""
horilla/settings/__init__.py

跃科高校人事系统统一设置入口。

规则：
1. base 是上游基础设置；addons/local_settings 只能做受控覆盖。
2. HR Authority 必须显式注册，不能依赖 AppConfig.ready() 偷改根 URL。
3. HR13~HR18 并行施工时只注册当前代码树真实存在的 Authority app。
4. 开发、CI、迁移验收、生产统一 MySQL；非 MySQL 配置直接 fail-closed。
"""

import os
from importlib.util import find_spec

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

# Client / deployment overrides are independent. A missing addons.py must not
# accidentally prevent local_settings.py from loading.
try:
    from .addons import *  # noqa: F401,F403
except ImportError:
    pass

try:
    from .local_settings import *  # noqa: F401,F403
except ImportError:
    pass

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
