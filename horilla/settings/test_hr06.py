"""
horilla/settings/test_hr06.py

HR06 验证专用 settings：继承 base，剔除并行施工中的半成品 app
（hr_external/hr_time 的 E034 索引名超长等系统检查错误由 HR08/HR11 会话负责修复，
在修复前会破坏 Django 启动）。仅用于 HR06 本地验证/测试，不影响生产 base.py。
"""

from horilla.settings.base import *  # noqa: F401,F403

_EXCLUDE = {"hr_external", "hr_time"}
INSTALLED_APPS = [a for a in INSTALLED_APPS if a not in _EXCLUDE]  # noqa: F405
