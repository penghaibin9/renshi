from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_control_center", "0004_alter_hrauthoritycutover_domain"),
    ]

    operations = [
        migrations.AlterField(
            model_name="hrauthoritycutover",
            name="domain",
            field=models.CharField(
                choices=[
                    ("ORGANIZATION", "Organization"),
                    ("STAFF", "Staff"),
                    ("ASSESSMENT", "Assessment"),
                    ("QUALIFICATION", "Qualification"),
                ],
                max_length=32,
            ),
        ),
    ]
