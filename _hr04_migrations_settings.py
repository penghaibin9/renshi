"""
临时设置（HR04 专用）：排除并发窗口未完成的 app，
仅用于生成 hr_recruitment migration 与跑 HR04 自身测试。不提交。
"""
from horilla.settings.base import *  # noqa

_EXCLUDE = {
    "hr_staff",
    "hr_time",
    "hr_external",
    "hr_onboarding",
}
INSTALLED_APPS = [
    app
    for app in INSTALLED_APPS
    if not any(app == e or app.startswith(e + ".") for e in _EXCLUDE)
]
