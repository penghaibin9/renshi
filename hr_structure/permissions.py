"""
hr_structure/permissions.py

HR02 权限码（总册 6.2 冻结）。通过 permission meta 注册到 DB。
"""

HR02_PERMISSIONS = (
    "hr.structure.access",
    "hr.organization.view",
    "hr.organization.create",
    "hr.organization.change.submit",
    "hr.organization.change.review",
    "hr.organization.change.approve",
    "hr.organization.manage",
    "hr.organization.history.view",
    "hr.organization.export",
    "hr.org_relation.view",
    "hr.org_relation.manage",
    "hr.staffing_plan.view",
    "hr.staffing_plan.create",
    "hr.staffing_plan.edit",
    "hr.staffing_plan.submit",
    "hr.staffing_plan.review",
    "hr.staffing_plan.approve",
    "hr.staffing_plan.activate",
    "hr.staffing_plan.export",
    "hr.post_catalog.view",
    "hr.post_catalog.manage",
    "hr.post_catalog.export",
    "hr.position.view",
    "hr.position.manage",
    "hr.position.freeze",
    "hr.position.close",
    "hr.position.export",
    "hr.reorg.preview",
    "hr.reorg.create",
    "hr.reorg.submit",
    "hr.reorg.review",
    "hr.reorg.approve",
    "hr.reorg.execute",
)


class HrStructurePermissionMeta(models.Model):
    """仅为注册 HR02 权限码（总册 6.2），无数据字段。"""

    class Meta:
        managed = False
        permissions = tuple(
            (code, code.replace(".", " ").title()) for code in HR02_PERMISSIONS
        )
