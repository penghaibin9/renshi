from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_external", "0018_mysql_active_exit_unique_backstop")]

    operations = [
        migrations.AddField(
            model_name="hrexternalprovisioningrequest",
            name="provider_receipt_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="hrexternalprovisioningrequest",
            name="next_attempt_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
