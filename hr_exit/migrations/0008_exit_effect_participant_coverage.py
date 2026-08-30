from django.db import migrations, models


PARTICIPANT_CHOICES = [
    ("PENDING", "Pending"),
    ("RUNNING", "Running"),
    ("SUCCESS", "Success"),
    ("FAILED", "Failed"),
    ("UNAVAILABLE", "Unavailable"),
    ("NOT_REQUIRED", "Not required"),
]


class Migration(migrations.Migration):
    dependencies = [("hr_exit", "0007_archive_transfer_receipt")]

    operations = [
        migrations.AddField(
            model_name="exiteffect",
            name="hr07_status",
            field=models.CharField(
                choices=PARTICIPANT_CHOICES,
                default="NOT_REQUIRED",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="exiteffect",
            name="hr07_receipt_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="exiteffect",
            name="asset_status",
            field=models.CharField(
                choices=PARTICIPANT_CHOICES,
                default="NOT_REQUIRED",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="exiteffect",
            name="asset_receipt_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="exiteffect",
            name="finance_status",
            field=models.CharField(
                choices=PARTICIPANT_CHOICES,
                default="NOT_REQUIRED",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="exiteffect",
            name="finance_receipt_json",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
