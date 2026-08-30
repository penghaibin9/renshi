"""
hr_structure/permissions.py

HR02 权限码（总册 6.2 冻结）。通过 permission meta 注册到 DB。
"""

HR02_PERMISSIONS = (
    "hr.structure.access",
    "hr.structure.organization.view",
    "hr.structure.organization.create",
    "hr.structure.organization.change.submit",
    "hr.structure.organization.change.review",
    "hr.structure.organization.change.approve",
    "hr.structure.organization.manage",
    "hr.structure.organization.history.view",
    "hr.structure.organization.export",
    "hr.structure.org_relation.view",
    "hr.structure.org_relation.manage",
    "hr.structure.staffing_plan.view",
    "hr.structure.staffing_plan.create",
    "hr.structure.staffing_plan.edit",
    "hr.structure.staffing_plan.submit",
    "hr.structure.staffing_plan.review",
    "hr.structure.staffing_plan.approve",
    "hr.structure.staffing_plan.activate",
    "hr.structure.staffing_plan.export",
    "hr.structure.post_catalog.view",
    "hr.structure.post_catalog.manage",
    "hr.structure.post_catalog.export",
    "hr.structure.position.view",
    "hr.structure.position.manage",
    "hr.structure.position.freeze",
    "hr.structure.position.close",
    "hr.structure.position.export",
    "hr.structure.reorg.preview",
    "hr.structure.reorg.create",
    "hr.structure.reorg.submit",
    "hr.structure.reorg.review",
    "hr.structure.reorg.approve",
    "hr.structure.reorg.execute",
)

# One-release compatibility for grants created before the canonical HR02 domain
# was frozen. New code and new grants must use ``hr.structure.*`` only.
LEGACY_HR02_PERMISSION_ALIASES = {
    code: code.replace("hr.structure.", "hr.", 1)
    for code in HR02_PERMISSIONS
    if code != "hr.structure.access"
}


def has_hr02_permission(user, permission_code: str) -> bool:
    """Check a registered HR02 permission with a bounded legacy fallback."""

    if permission_code not in HR02_PERMISSIONS:
        return False
    if getattr(user, "is_superuser", False) or user.has_perm(permission_code):
        return True
    legacy_code = LEGACY_HR02_PERMISSION_ALIASES.get(permission_code)
    return bool(legacy_code and user.has_perm(legacy_code))


__all__ = (
    "HR02_PERMISSIONS",
    "LEGACY_HR02_PERMISSION_ALIASES",
    "has_hr02_permission",
)
