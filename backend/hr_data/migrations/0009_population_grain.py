from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_data", "0008_quality_rule_execution"),
    ]

    operations = [
        migrations.AddField(
            model_name="populationdefinitionversion",
            name="grain",
            field=models.CharField(
                choices=[
                    ("UNSPECIFIED", "Legacy / unspecified"),
                    ("PERSON", "Person"),
                    ("STAFF", "Staff"),
                    ("EMPLOYMENT_RELATIONSHIP", "Employment relationship"),
                    ("ASSIGNMENT", "Assignment"),
                ],
                db_index=True,
                default="UNSPECIFIED",
                max_length=32,
            ),
        ),
        migrations.AddIndex(
            model_name="populationdefinitionversion",
            index=models.Index(
                fields=["tenant_id", "grain", "status"],
                name="idx_hr18_population_grain",
            ),
        ),
    ]
