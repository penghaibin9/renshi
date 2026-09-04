from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("geofencing", "0001_initial")]

    operations = [
        # company_id is already a OneToOneField, whose database unique index
        # enforces the same non-null invariant on every supported backend.
        migrations.RemoveConstraint(
            model_name="geofencing",
            name="unique_company_id_when_not_null_geofencing",
        ),
    ]
