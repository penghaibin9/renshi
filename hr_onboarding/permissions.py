"""
hr_onboarding/permissions.py

HR05 权限码（《05_HR05_入职管理_施工总册_终极版》§5 冻结）。
通过 permission meta 注册到 DB（与 hr_structure/hr_recruitment 同模式）。

原则：
- 一个 IT 任务执行人可以看到"为工号 X 开通邮箱"，但没有理由看到身份证、体检、薪资或完整简历。
- 越权不能靠 200 + empty list 模糊掉；无权限 → 403。
"""

from django.core.exceptions import PermissionDenied
from django.db import models

# fmt: off
HR05_PERMISSIONS = (
    # 通用 case 权限
    "hr05.case.view",
    "hr05.case.create",
    "hr05.case.cancel",
    "hr05.case.activate",
    "hr05.activation_fact.correct",
    "hr05.activation_fact.revoke",
    # HR05-02 报到登记
    "hr05.report.checkin",
    # HR05-03 材料核验
    "hr05.material.review",
    "hr05.material.sensitive_view",
    # HR05-04 协同任务
    "hr05.task.manage",
    "hr05.task.complete",
    "hr05.task.waive",
    # 身份/岗位 provisioning
    "hr05.identity.provision",
    "hr05.position.commit",
    # HR05-05 试用转正
    "hr05.probation.manage",
    "hr05.probation.finalize",
    # 导出
    "hr05.export",
    "hr05.sensitive_export",
)
# fmt: on


class HrOnboardingPermissionMeta(models.Model):
    """仅为注册 HR05 权限码（总册 §5），无数据字段。"""

    class Meta:
        managed = False
        app_label = "hr_onboarding"
        permissions = tuple(
            (code, code.replace(".", " ").title()) for code in HR05_PERMISSIONS
        )


def require_hr05_permission(perm_code):
    """
    校验 request.user 拥有 HR05 权限码。

    返回 view decorator。无权限 → PermissionDenied（403），
    不允许用 200 + empty 伪装。
    """
    from functools import wraps

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied("UNAUTHENTICATED")
            if not (request.user.is_superuser or request.user.has_perm(perm_code)):
                raise PermissionDenied("PERMISSION_DENIED")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
