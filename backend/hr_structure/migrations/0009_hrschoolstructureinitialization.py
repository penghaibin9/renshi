"""Record initial structure commands without rewriting existing business facts."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_structure", "0008_hrpositionversion")]

    operations = [
        migrations.CreateModel(
            name="HrSchoolStructureInitialization",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_id", models.BigIntegerField(unique=True)),
                ("request_hash", models.CharField(max_length=64)),
                ("created_by", models.CharField(max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("catalog_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="hr_structure.hrpostcatalogversion")),
                ("department_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="initial_department_receipts", to="hr_structure.hrorganizationversion")),
                ("position", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="hr_structure.hrposition")),
                ("root_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="initial_school_receipts", to="hr_structure.hrorganizationversion")),
            ],
            options={"default_permissions": ()},
        ),
    ]
