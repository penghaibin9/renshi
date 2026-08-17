"""
horilla/settings/test_hr05.py

HR05 独立验证/测试 settings：继承 base，排除其他窗口的半成品 app
（hr_recruitment/models 导入断裂/ hr_time.models.policy 缺失/ hr_changes/hr_contracts 不稳定
等均会破坏 Django 启动）。保留 hr_onboarding 及其稳定依赖：

- hr_structure (HR02 ✅ 已交付)
- hr_staff (HR03 ✅ 已交付)
- hr_control_center (HR01 ✅ 已交付)
- hr_recruitment (HR04 ⚠️ 只要常量/enum 不加载 models)
- employee / base / onboarding (legacy 引用)
- auth / audit / documents / notifications (基础设施)
"""

from horilla.settings.base import *  # noqa: F401,F403

_EXCLUDE = {
    "hr_time",           # models.policy 不存在 → ImportError
    "hr_external",       # 并行窗口施工中
    "hr_changes",        # 未开窗
    "hr_contracts",      # 未开窗
    "hr_recruitment",    # models/__init__.py import HrAssessmentParticipant 不存在
}
INSTALLED_APPS = [a for a in INSTALLED_APPS if a not in _EXCLUDE]  # noqa: F405
