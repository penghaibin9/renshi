"""
临时设置（HR04 专用）：排除并发窗口未完成/损坏的 app（不越界修复）。
hr_staff/hr_time 已恢复参与（可正常 import）。不提交。
"""
from horilla.settings.base import *  # noqa

_EXCLUDE = {
    "hr_external",  # SyntaxError（HR08）
    "hr_changes",   # import hr_staff 失败（HR06 接线中）
    "hr_onboarding",
}
INSTALLED_APPS = [
    app
    for app in INSTALLED_APPS
    if not any(app == e or app.startswith(e + ".") for e in _EXCLUDE)
]

# hr_time（HR11）索引名超长 E034 是并发窗口问题，测试隔离 settings 静默该检查（不越界修复）
SILENCED_SYSTEM_CHECKS = ["models.E034"]
