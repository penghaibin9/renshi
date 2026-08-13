from django.db import migrations


def create_workflow_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    content_type = ContentType.objects.get(
        app_label="hr_appointment",
        model="appointmentpolicyversion",
    )
    for codename, name in (
        ("hr.appointment.application", "办理 HR14 岗位竞聘申报"),
        ("hr.appointment.manage", "管理 HR14 竞聘批次与资格审查"),
    ):
        Permission.objects.get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )


def remove_workflow_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(
        content_type__app_label="hr_appointment",
        content_type__model="appointmentpolicyversion",
        codename__in=["hr.appointment.application", "hr.appointment.manage"],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("hr_appointment", "0011_appointment_effect_permission"),
    ]

    operations = [
        migrations.RunPython(
            create_workflow_permissions,
            remove_workflow_permissions,
        ),
    ]
