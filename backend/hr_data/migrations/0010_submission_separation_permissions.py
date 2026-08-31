from django.db import migrations


PERMISSIONS = (
    ("hr.data.approve", "审批 HR18 正式数据报送"),
    ("hr.data.receipt", "登记 HR18 外部正式报送回执"),
)


def create_separated_submission_permissions(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    content_type, _created = ContentType.objects.get_or_create(
        app_label="hr_data",
        model="metricdefinitionversion",
    )
    for codename, name in PERMISSIONS:
        Permission.objects.get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )


def remove_separated_submission_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(
        content_type__app_label="hr_data",
        content_type__model="metricdefinitionversion",
        codename__in=[codename for codename, _name in PERMISSIONS],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("hr_data", "0009_population_grain"),
    ]

    operations = [
        migrations.RunPython(
            create_separated_submission_permissions,
            remove_separated_submission_permissions,
        ),
    ]
