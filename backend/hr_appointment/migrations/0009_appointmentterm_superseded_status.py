from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_appointment", "0008_term_governance_authority"),
    ]

    operations = [
        migrations.AlterField(
            model_name="appointmentterm",
            name="status",
            field=models.CharField(
                choices=[
                    ("ACTIVE", "Active"),
                    ("EXPIRING", "Expiring"),
                    ("RENEWAL_IN_PROGRESS", "Renewal in progress"),
                    ("RENEWED", "Renewed"),
                    ("SUPERSEDED", "Superseded by successor term"),
                    ("EXPIRED", "Expired"),
                    ("TERMINATED", "Terminated"),
                    ("REAPPOINTMENT_REQUIRED", "Reappointment required"),
                ],
                db_index=True,
                default="ACTIVE",
                max_length=32,
            ),
        ),
    ]
