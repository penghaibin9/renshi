"""
hr_time/permissions.py

HR11 权限合同（总册 §151-153）。

原则：
- “登录” ≠ “可看全校考勤/假期”。
- 每个 HR11 endpoint 先过 tenant → permission → data scope 三层校验。
- 越权不能靠 200 + empty list 模糊掉。
"""

from django.core.exceptions import PermissionDenied

from hr_time.constants import TimePermissionCode

# fmt: off
HR11_PERMISSION_ROLES = {
    "HR11_TIME_ADMIN": TimePermissionCode.HR11_TIME_ADMIN,
    "HR11_POLICY_MANAGER": TimePermissionCode.HR11_POLICY_MANAGER,
    "HR11_SCHEDULE_MANAGER": TimePermissionCode.HR11_SCHEDULE_MANAGER,
    "HR11_ATTENDANCE_MANAGER": TimePermissionCode.HR11_ATTENDANCE_MANAGER,
    "HR11_ATTENDANCE_VERIFIER": TimePermissionCode.HR11_ATTENDANCE_VERIFIER,
    "HR11_LEAVE_ADMIN": TimePermissionCode.HR11_LEAVE_ADMIN,
    "HR11_LEAVE_APPROVER": TimePermissionCode.HR11_LEAVE_APPROVER,
    "HR11_OVERTIME_APPROVER": TimePermissionCode.HR11_OVERTIME_APPROVER,
    "HR11_PERIOD_CLOSER": TimePermissionCode.HR11_PERIOD_CLOSER,
    "HR11_AUDITOR": TimePermissionCode.HR11_AUDITOR,
    "HR11_EMPLOYEE_SELF": TimePermissionCode.HR11_EMPLOYEE_SELF,
    "HR11_MANAGER_TEAM": TimePermissionCode.HR11_MANAGER_TEAM,
    "HR11_DEVICE_ADMIN": TimePermissionCode.HR11_DEVICE_ADMIN,
    "HR11_READ_ANALYTICS": TimePermissionCode.HR11_READ_ANALYTICS,
}
# fmt: on


def require_hr11_permission(perm_code):
    """
    校验 request.user 拥有 HR11 权限码。

    返回 view decorator。无权限 → PermissionDenied（403），
    不允许用 200 + empty 伪装。
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
