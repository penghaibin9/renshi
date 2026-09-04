from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_recruitment", "0013_mysql_application_no_unique_backstop")]

    operations = [
        migrations.AddField(
            model_name="hrrecruitmentcandidate",
            name="legal_hold",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="hrrecruitmentcandidate",
            name="legal_hold_reason",
            field=models.CharField(blank=True, default="", max_length=300),
        ),
        migrations.AddField(
            model_name="hrrecruitmentcandidate",
            name="anonymized_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hrapplicationmaterial",
            name="purged_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
