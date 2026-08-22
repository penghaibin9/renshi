from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_qualification", "0004_alter_hrdoubleteacherrule_dimension_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="hrdoubleteacherevidencepackage",
            name="frozen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
