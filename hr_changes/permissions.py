"""
hr_changes/permissions.py —— HR06 权限合同（S1）。

原则（总册 §41 + 00 §28.2）：
- 统一 `hr.change.*` 权限码；旧 `hr06.*` 走 PermissionAlias 迁移，不重复授权。
- "登录" ≠ "可看全校异动"；endpoint 先过 tenant + permission + data scope。
- correction/rescind 为高权限码，不得用普通 view 权限绕过。
"""

from django.core.exceptions import PermissionDenied

from hr_changes.constants import HR_CHANGE_PERMISSIONS

__all__ = ["HR_CHANGE_PERMISSIONS", "require_hr_change_permission"]


def require_hr_change_permission(perm_code):
    """校验 request.user 拥有 HR06 权限码。无权限 → PermissionDenied（403）。"""

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
