"""
horilla/settings/test_hr02.py

HR02 验证专用 settings：继承 base，剔除并行施工中的半成品 app
（hr_time/hr_staff/hr_recruitment/hr_external 由其他会话负责，其 ready()/models
尚不稳定会破坏 Django 启动）。仅用于 HR02 本地验证/测试，不影响生产 base.py。
"""

from horilla.settings.base import *  # noqa: F401,F403

_EXCLUDE = {"hr_time", "hr_staff", "hr_recruitment", "hr_external"}
INSTALLED_APPS = [a for a in INSTALLED_APPS if a not in _EXCLUDE]  # noqa: F405

# 移除会因半成品 app 缺 models 而崩溃的副作用
