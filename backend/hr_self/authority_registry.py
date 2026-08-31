"""Canonical HR17 permission contract.

HR17 is an experience Authority and deliberately emits no business-fact
events. Source facts remain owned by HR03-HR16.
"""

from horilla.hr_permission_registry import PermissionDefinition, register_permissions

PERM_SELF_VIEW = "hr.self.view"

register_permissions(
    (
        PermissionDefinition(
            PERM_SELF_VIEW,
            "HR17",
            "访问当前登录教职工本人的聚合服务",
        ),
    )
)
