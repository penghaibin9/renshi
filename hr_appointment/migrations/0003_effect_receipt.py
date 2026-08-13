from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_appointment", "0002_align_position_refs_and_effect_pending")]

    operations = [
        migrations.AddField(
            model_name="positionappointmentfact",
            name="reservation_id",
            field=models.PositiveBigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="positionappointmentfact",
            name="effect_receipt_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="positionappointmentfact",
            name="last_effect_error",
            field=models.TextField(blank=True, default=""),
        ),
    ]
