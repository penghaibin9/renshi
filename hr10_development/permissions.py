"""
hr10_development/permissions.py

HR10 权限执行层（00 §28.2 Prefix: hr.development）。

通过 permission meta 注册到 DB（与 hr_recruitment/permissions.py 同模式）。

原则：
- "登录" ≠ "可看全校发展数据"。
- 所有 HR10 endpoint 必须先过 tenant + data scope + permission 三层校验。
- 越权不能靠 200 + empty list 模糊掉；无权限 → 403。
"""

from django.core.exceptions import PermissionDenied
from django.db import models

# fmt: off
HR10_PERMISSIONS = (
    # HR10-01 教师发展计划
    "hr.development.plan.view",
    "hr.development.plan.create",
    "hr.development.plan.approve",
    "hr.development.plan.publish",
    # HR10-02 培训项目
    "hr.development.program.view",
    "hr.development.program.manage",
    "hr.development.program.publish",
    # HR10-03 报名与审批
    "hr.development.request.view",
    "hr.development.request.create",
    "hr.development.request.approve",
    "hr.development.request.review_budget",
    # HR10-04 企业实践
    "hr.development.practice.view",
    "hr.development.practice.manage",
    "hr.development.practice.publish",
    # HR10-05 过程与成果
    "hr.development.process.record",
    "hr.development.completion.verify",
    "hr.development.evaluation.manage",
    "hr.development.output.verify",
    # HR10-06 发展档案
    "hr.development.record.view",
    "hr.development.analytics.read",
    "hr.development.audit",
    "hr.development.import.manage",
)
# fmt: on


class Hr10DevelopmentPermissionMeta(models.Model):
    """仅为注册 HR10 权限码（总册 §148），无数据字段。"""

    class Meta:
        managed = False
        app_label = "hr10_development"
        permissions = tuple(
            (code, code.replace(".", " ").title()) for code in HR10_PERMISSIONS
        )


def require_hr10_permission(perm_code):
    """
    校验 request.user 拥有 HR10 权限码。

    返回 view decorator。无权限 → PermissionDenied（403）。
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
