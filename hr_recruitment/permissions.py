"""
hr_recruitment/permissions.py

HR04 权限码（《04_HR04_招聘与人才引进_施工总册_终极版》第 6.3 节冻结）。
通过 permission meta 注册到 DB（与 hr_structure/permissions.py、hr_control_center 同模式）。

原则：
- "登录" ≠ "可看全校候选人"。
- 所有 HR04 endpoint 必须先过 tenant + data scope + permission 三层校验。
- 越权不能靠 200 + empty list 模糊掉；无权限 → 403。
"""

from django.core.exceptions import PermissionDenied
from django.db import models

# fmt: off
HR04_PERMISSIONS = (
    # HR04-01 年度用人计划
    "hr04.plan.view",
    "hr04.plan.create",
    "hr04.plan.approve",
    # HR04-02 招聘项目与岗位
    "hr04.campaign.view",
    "hr04.campaign.manage",
    "hr04.campaign.publish",
    # HR04-03 人才库与应聘者
    "hr04.application.view",
    "hr04.application.manage",
    "hr04.application.sensitive_view",
    "hr04.application.export",
    # HR04-04 资格审查
    "hr04.qualification.review",
    "hr04.qualification.finalize",
    # HR04-05 考试面试与考察
    "hr04.assessment.manage",
    "hr04.assessment.score",
    "hr04.assessment.score_override",
    "hr04.assessment.unlock_score",
    # HR04-06 录用与人才引进
    "hr04.proposed_hire.manage",
    "hr04.public_notice.publish",
    "hr04.offer.manage",
    "hr04.handoff_hr05",
)
# fmt: on


class HrRecruitmentPermissionMeta(models.Model):
    """仅为注册 HR04 权限码（总册 6.3），无数据字段。"""

    class Meta:
        managed = False
        app_label = "hr_recruitment"
        permissions = tuple(
            (code, code.replace(".", " ").title()) for code in HR04_PERMISSIONS
        )


def require_hr04_permission(perm_code):
    """
    校验 request.user 拥有 HR04 权限码。

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
