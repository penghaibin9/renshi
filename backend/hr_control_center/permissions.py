"""
hr_control_center/permissions.py

HR01 独立权限合同（冻结于施工总册 6.2）。

原则：
- “登录” ≠ “可看全校人事统计”。
- 所有 HR01 endpoint 必须先过 tenant + permission + data scope 三层校验。
- 越权不能靠 200 + empty list 模糊掉。
"""

from django.core.exceptions import PermissionDenied


# fmt: off
HR_DASHBOARD_PERMISSIONS = (
    "hr.dashboard.view",
    "hr.dashboard.overview.view",
    "hr.dashboard.todo.view",
    "hr.dashboard.todo.supervise",
    "hr.dashboard.alert.view",
    "hr.dashboard.alert.manage",
    "hr.dashboard.workforce.view",
    "hr.dashboard.workforce.drilldown",
    "hr.dashboard.quick_action.use",
    "hr.dashboard.export",
    "hr.dashboard.sensitive_metrics.view",
)
# fmt: on

# 敏感指标（默认不读，读取需专项权限 hr.dashboard.sensitive_metrics.view）
SENSITIVE_METRIC_KEYS = frozenset(
    {
        "salary_total",
        "salary_average",
        "id_card_coverage",
        "bank_account_coverage",
    }
)


def require_hr_permission(perm_code):
    """
    校验 request.user 拥有 HR01 权限码。

    返回一个 view decorator。无权限 → PermissionDenied（403），
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
