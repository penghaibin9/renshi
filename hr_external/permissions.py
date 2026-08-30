"""
hr_external/permissions.py —— HR08 权限合同（S1）。

原则（总册 §88/§89/§90 + HR03 经验）：
- "登录" ≠ "可看全校外聘人才"；
- 所有 HR08 endpoint 先过 tenant + permission + data scope 三层校验；
- 越权不能靠 200 + empty list 模糊掉（fail-closed）；
- 字段级权限：即使有 hr08.profile.view，SENSITIVE/HIGH_SENSITIVE 字段仍需
  hr08.profile.sensitive_view。
"""

from django.core.exceptions import PermissionDenied

from horilla.hr_permission_registry import PermissionDefinition, register_permissions


_PERMISSION_DESCRIPTIONS = {
    "profile.view": "查看本校外聘人员业务档案",
    "profile.create": "创建本校外聘人员业务档案",
    "profile.sensitive_view": "查看外聘人员受限敏感字段",
    "profile.export": "导出外聘人员受控数据",
    "industry.view": "查看产业导师与企业实践事实",
    "industry.manage": "维护产业导师与企业实践事实",
    "hiring.create": "发起外聘聘用申请",
    "hiring.review": "复核外聘聘用申请",
    "hiring.approve": "审批外聘聘用申请",
    "hiring.activate": "激活已满足协议要求的外聘聘任",
    "task.view": "查看外聘任务与派任",
    "task.manage": "维护外聘任务与派任",
    "task.verify": "核验外聘任务完成事实",
    "workload.verify": "核验外聘工作量事实",
    "renewal.review": "查看外聘续聘评审",
    "renewal.decide": "作出外聘续聘决定",
    "exit.manage": "执行外聘到期与终止流程",
    "access.view": "查看外聘系统权限与回执",
    "access.manage": "下发或回收外聘系统权限",
}

PERMISSION_DEFINITIONS = tuple(
    PermissionDefinition(
        f"hr.external.{action}",
        "HR08",
        description,
    )
    for action, description in _PERMISSION_DESCRIPTIONS.items()
)
register_permissions(PERMISSION_DEFINITIONS)

# 公开对外聘本人开放的最小权限（External Teacher Portal，§90）。
# 仅列出本人门户所需子集；完整权限码见 constants.HR08_PERMISSIONS。
SELF_VIEW_PERMISSIONS = frozenset(
    {"hr08.task.view", "hr08.profile.view", "hr08.access.view"}
)


def require_hr_external_permission(perm_code):
    """
    校验 request.user 拥有 HR08 权限码。无权限 → PermissionDenied（403）。
    """

    def decorator(view_func):
        from functools import wraps

        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied("UNAUTHENTICATED")
            if not (request.user.is_superuser or request.user.has_perm(perm_code)):
                raise PermissionDenied("PERMISSION_DENIED")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def has_sensitive_view(user, level="SENSITIVE"):
    """
    字段级权限判定：
    - SENSITIVE → hr08.profile.sensitive_view
    - HIGH_SENSITIVE → 同样需要 hr08.profile.sensitive_view（更高层 reveal 在 S3 引入）
    仅做最小层判定，具体字段映射由 policies 层给出。
    """
    if user.is_superuser:
        return True
    if level in ("SENSITIVE", "HIGH_SENSITIVE"):
        return user.has_perm("hr08.profile.sensitive_view")
    return True


def can_view_self(user):
    """本人门户最小权限判定（§90）。"""
    if user.is_superuser:
        return True
    return bool(SELF_VIEW_PERMISSIONS & set(user.get_all_permissions()))
