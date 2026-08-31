from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_appointment", "0009_appointmentterm_superseded_status"),
    ]

    operations = [
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
                    ("WAITLIST", "Waitlist after final ranking"),
                    ("NOT_SELECTED", "Not selected after final ranking"),
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
    ]
