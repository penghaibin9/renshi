from django.db import migrations


def create_submission_permission(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    content_type, _created = ContentType.objects.get_or_create(
        app_label="hr_data",
        model="metricdefinitionversion",
    )
    Permission.objects.get_or_create(
        content_type=content_type,
        codename="hr.data.submit",
        defaults={"name": "执行 HR18 正式数据报送与回执"},
    )


def remove_submission_permission(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(
        content_type__app_label="hr_data",
        content_type__model="metricdefinitionversion",
        codename="hr.data.submit",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("hr_data", "0004_asof_evidence_snapshot"),
    ]

    operations = [
        migrations.RunPython(
            create_submission_permission,
            remove_submission_permission,
        ),
    ]
