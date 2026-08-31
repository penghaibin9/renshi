from django.db import migrations


def create_result_permission(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    content_type, _created = ContentType.objects.get_or_create(
        app_label="hr_title",
        model="titleapplicationcase",
    )
    Permission.objects.get_or_create(
        content_type=content_type,
        codename="hr.title.result",
        defaults={"name": "发布、修订与撤销 HR13 正式职称结果"},
    )


def remove_result_permission(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(
        content_type__app_label="hr_title",
        content_type__model="titleapplicationcase",
        codename="hr.title.result",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("hr_title", "0006_publicity_appeal_authority"),
    ]

    operations = [
        migrations.RunPython(create_result_permission, remove_result_permission),
    ]
