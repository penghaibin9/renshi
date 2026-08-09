"""
hr_time/tests_settings.py

HR11 测试专用 settings：继承项目 base settings，隔离并行窗口的半成品 app。

原因（2026-08-09 共享工作区并行施工）：
- hr_recruitment（HR04）models 引用未落盘的模块 → 阻塞 app 加载；
- hr_external（HR08）存在 models.E034 / admin.E035 未收敛问题 → 阻塞 system check。

本文件只在 HR11 测试命令中通过 --settings 使用，不改共享 horilla/settings/base.py，
不对并行窗口代码做任何修改（不越界）。
"""

from horilla.settings.base import *  # noqa: F401,F403

# 排除并行窗口的半成品 app（HR11 测试不依赖它们）
_EXCLUDE_APPS = {
    "hr_recruitment",
    "hr_external",
    "hr_onboarding",
    "hr_staff",  # HR03 并行窗口正在施工（import_service 间歇性语法错误），HR11 无 FK 依赖
}

INSTALLED_APPS = [app for app in INSTALLED_APPS if app not in _EXCLUDE_APPS]

SILENCED_SYSTEM_CHECKS = [
    "models.E034",
    "admin.E035",
]
