from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_data", "0005_submission_permission"),
    ]

    operations = [
        migrations.AlterField(
            model_name="submissionsnapshot",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("VALIDATED", "Validated"),
                    ("APPROVED", "Approved"),
                    ("DISPATCH_QUEUED", "Async dispatch queued"),
                    ("SUBMITTED", "Submitted"),
                    ("ACCEPTED", "Accepted"),
                    ("REJECTED", "Rejected"),
                    ("CORRECTED", "Corrected"),
                ],
                db_index=True,
                default="DRAFT",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="submissionsnapshot",
            name="dispatch_ref",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="submissionsnapshot",
            name="dispatch_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
