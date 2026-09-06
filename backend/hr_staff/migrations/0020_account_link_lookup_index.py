"""Index explicit SELF account lookups without changing historical link facts."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_staff", "0019_material_ticket_constraints"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="hraccountlink",
            index=models.Index(
                fields=["tenant_id", "auth_user_id", "link_status"],
                name="hr_account_tenant_user_status",
            ),
        ),
    ]
