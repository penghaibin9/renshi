import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_assessment", "0010_provider_snapshot_authority"),
    ]

    operations = [
        migrations.CreateModel(
            name="HrLegacyPmsWriterSeal",
            fields=[
                (
                    "key",
                    models.CharField(
                        default="PMS_FORMAL_WRITER",
                        editable=False,
                        max_length=50,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("is_frozen", models.BooleanField(db_index=True, default=False)),
                ("revision", models.PositiveBigIntegerField(default=0)),
                ("reason", models.CharField(blank=True, default="", max_length=500)),
                ("operator", models.CharField(blank=True, default="SYSTEM", max_length=150)),
                ("frozen_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Legacy PMS writer seal",
                "db_table": "hr_assessment_legacy_pms_writer_seal",
            },
        ),
        migrations.CreateModel(
            name="HrLegacyPmsWriterSealEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(max_length=20)),
                ("revision", models.PositiveBigIntegerField()),
                ("reason", models.CharField(blank=True, default="", max_length=500)),
                ("operator", models.CharField(default="SYSTEM", max_length=150)),
                ("occurred_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "verbose_name": "Legacy PMS writer seal event",
                "db_table": "hr_assessment_legacy_pms_writer_seal_event",
                "ordering": ("-occurred_at",),
            },
        ),
    ]
