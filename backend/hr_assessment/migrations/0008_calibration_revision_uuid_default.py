import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_assessment", "0007_case_staff_lookup_index")]

    operations = [
        migrations.AlterField(
            model_name="hrcalibrationrevision",
            name="id",
            field=models.UUIDField(
                primary_key=True,
                default=uuid.uuid4,
                editable=False,
                serialize=False,
            ),
        ),
    ]
