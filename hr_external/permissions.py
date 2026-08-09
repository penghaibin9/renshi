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
