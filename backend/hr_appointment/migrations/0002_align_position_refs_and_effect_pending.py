from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_appointment", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="appointmentapplicationcase",
            name="position_instance_id",
            field=models.PositiveBigIntegerField(),
        ),
        migrations.AlterField(
            model_name="appointmentapplicationcase",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("SUBMITTED", "Submitted"),
                    ("RETURNED", "Returned for correction"),
                    ("ELIGIBLE", "Eligibility passed"),
                    ("REJECTED", "Rejected"),
                    ("WITHDRAWN", "Withdrawn"),
                    ("UNDER_REVIEW", "Under review"),
                    ("PROPOSED", "Proposed appointment"),
                    ("PUBLICITY", "Publicity"),
                    ("EFFECT_PENDING", "Final, waiting for HR03 effect"),
                    ("EFFECTIVE", "Effective"),
                    ("CANCELLED", "Cancelled"),
                ],
                db_index=True,
                default="DRAFT",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="positionappointmentfact",
            name="position_instance_id",
            field=models.PositiveBigIntegerField(),
        ),
        migrations.AlterField(
            model_name="positionappointmentfact",
            name="status",
            field=models.CharField(
                choices=[
                    ("EFFECT_PENDING", "Final, waiting for HR03 effect"),
                    ("EFFECTIVE", "Effective"),
                    ("REVISED", "Revised"),
                    ("ENDED", "Ended"),
                    ("REVOKED", "Revoked"),
                ],
                db_index=True,
                default="EFFECT_PENDING",
                max_length=16,
            ),
        ),
    ]
