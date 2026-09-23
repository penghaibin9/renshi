"""Shorten the HR10 canonical fact UUID index name for Django portability."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("hr10_development", "0028_hr10_staff_identity_guards"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="hrdevelopmentfact",
            old_name="hr_dev_fact_uuid_type_valid_idx",
            new_name="hr10_fact_uuid_type_valid_idx",
        ),
    ]
