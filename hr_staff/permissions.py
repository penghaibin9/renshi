"""
hr_staff/permissions.py —— HR03 权限合同（S1）。

原则（总册 §39 + HR01 经验）：
- “登录” ≠ “可看全校教职工”。
- 所有 HR03 endpoint 先过 tenant + permission + data scope 三层校验。
- 越权不能靠 200 + empty list 模糊掉。
- 字段级权限：即使有 hr.staff.view，SENSITIVE/HIGH_SENSITIVE 字段仍需 view_sensitive / reveal_high_sensitive。
"""

from django.core.exceptions import PermissionDenied

from hr_staff.constants import HR_STAFF_PERMISSIONS


def require_hr_staff_permission(perm_code):
    """
    校验 request.user 拥有 HR03 权限码。无权限 → PermissionDenied（403）。
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
    - SENSITIVE → hr.staff.view_sensitive
    - HIGH_SENSITIVE → hr.staff.reveal_high_sensitive
    仅做最小层判定，具体字段映射由 policies 层给出。
    """
    if user.is_superuser:
        return True
    if level == "HIGH_SENSITIVE":
        return user.has_perm("hr.staff.reveal_high_sensitive")
    return user.has_perm("hr.staff.view_sensitive")
