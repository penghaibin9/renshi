from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("facedetection", "0002_alter_facedetection_start")]

    operations = [
        # company_id is already a OneToOneField, whose database unique index
        # enforces the same non-null invariant on every supported backend.
        migrations.RemoveConstraint(
            model_name="facedetection",
            name="unique_company_id_when_not_null_facedetection",
        ),
    ]
