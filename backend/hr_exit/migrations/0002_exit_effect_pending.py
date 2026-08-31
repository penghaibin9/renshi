from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_exit", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="exitcase",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("SUBMITTED", "Submitted"),
                    ("RETURNED", "Returned for correction"),
                    ("APPROVED", "Approved"),
                    ("REJECTED", "Rejected"),
                    ("HANDOVER", "Handover"),
                    ("SETTLEMENT", "Settlement"),
                    ("EFFECT_PENDING", "Waiting for HR03 employment effect"),
                    ("EFFECTIVE", "Effective"),
                    ("CANCELLED", "Cancelled"),
                ],
                db_index=True,
                default="DRAFT",
                max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="exitfact",
            name="status",
            field=models.CharField(
                choices=[
                    ("EFFECT_PENDING", "Waiting for HR03 employment effect"),
                    ("EFFECTIVE", "Effective"),
                    ("REVISED", "Revised"),
                    ("REVOKED", "Revoked"),
                ],
                db_index=True,
                default="EFFECT_PENDING",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="exitfact",
            name="effect_receipt_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="exitfact",
            name="last_effect_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="retirementfact",
            name="status",
            field=models.CharField(
                choices=[
                    ("EFFECT_PENDING", "Waiting for HR03 employment effect"),
                    ("EFFECTIVE", "Effective"),
                    ("REVISED", "Revised"),
                    ("REVOKED", "Revoked"),
                ],
                db_index=True,
                default="EFFECTIVE",
                max_length=16,
            ),
        ),
    ]
