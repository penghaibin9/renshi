from django.db import migrations, models


HR02_PERMISSIONS = (
    "hr.structure.access", "hr.structure.organization.view",
    "hr.structure.organization.create", "hr.structure.organization.change.submit",
    "hr.structure.organization.change.review", "hr.structure.organization.change.approve",
    "hr.structure.organization.manage", "hr.structure.organization.history.view",
    "hr.structure.organization.export", "hr.structure.org_relation.view",
    "hr.structure.org_relation.manage", "hr.structure.staffing_plan.view",
    "hr.structure.staffing_plan.create", "hr.structure.staffing_plan.edit",
    "hr.structure.staffing_plan.submit", "hr.structure.staffing_plan.review",
    "hr.structure.staffing_plan.approve", "hr.structure.staffing_plan.activate",
    "hr.structure.staffing_plan.export", "hr.structure.post_catalog.view",
    "hr.structure.post_catalog.manage", "hr.structure.post_catalog.export",
    "hr.structure.position.view", "hr.structure.position.manage",
    "hr.structure.position.freeze", "hr.structure.position.close",
    "hr.structure.position.export", "hr.structure.reorg.preview",
    "hr.structure.reorg.create", "hr.structure.reorg.submit",
    "hr.structure.reorg.review", "hr.structure.reorg.approve",
    "hr.structure.reorg.execute",
)


class Migration(migrations.Migration):
    dependencies = [("hr_structure", "0006_hrorganizationversion_uniq_hr_org_version_no")]

    operations = [
        migrations.CreateModel(
            name="HrStructurePermissionMeta",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
            ],
            options={
                "managed": False,
                "permissions": tuple(
                    (code, code.replace("hr.", "HR ").replace(".", ": ").title())
                    for code in HR02_PERMISSIONS
                ),
            },
        ),
    ]
