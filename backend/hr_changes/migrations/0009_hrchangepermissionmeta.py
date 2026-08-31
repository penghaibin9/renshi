from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_changes", "0008_trusted_effect_provider_boundary")]

    operations = [
        migrations.CreateModel(
            name="HrChangePermissionMeta",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
            ],
            options={
                "managed": False,
                "permissions": (
                    ("hr.change.view", "Hr Change View"),
                    ("hr.change.create", "Hr Change Create"),
                    ("hr.change.submit", "Hr Change Submit"),
                    ("hr.change.approve", "Hr Change Approve"),
                    ("hr.change.apply", "Hr Change Apply"),
                    ("hr.change.cancel", "Hr Change Cancel"),
                    ("hr.change.rescind", "Hr Change Rescind"),
                    ("hr.change.correct", "Hr Change Correct"),
                    ("hr.change.override_warning", "Hr Change Override_Warning"),
                    ("hr.change.transfer.create", "Hr Change Transfer Create"),
                    (
                        "hr.change.identity_change.create",
                        "Hr Change Identity_Change Create",
                    ),
                    ("hr.change.temporary.create", "Hr Change Temporary Create"),
                    ("hr.change.bulk.create", "Hr Change Bulk Create"),
                    ("hr.change.ledger.view", "Hr Change Ledger View"),
                    ("hr.change.ledger.export", "Hr Change Ledger Export"),
                ),
            },
        ),
    ]
