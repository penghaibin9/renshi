import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_title", "0002_title_view_permission")]

    operations = [
        migrations.CreateModel(
            name="TitleMaterialSnapshot",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("material_no", models.CharField(max_length=64)),
                ("application_case_id", models.UUIDField()),
                ("material_type", models.CharField(max_length=64)),
                ("display_name", models.CharField(max_length=200)),
                ("source_domain", models.CharField(default="SELF", max_length=32)),
                ("source_ref", models.CharField(blank=True, default="", max_length=128)),
                ("source_version", models.CharField(blank=True, default="", max_length=64)),
                ("content_hash", models.CharField(max_length=64)),
                ("snapshot_json", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ATTACHED", "Attached"),
                            ("RETURNED", "Returned for correction"),
                            ("ACCEPTED", "Accepted"),
                            ("WITHDRAWN", "Withdrawn"),
                        ],
                        db_index=True,
                        default="ATTACHED",
                        max_length=16,
                    ),
                ),
                ("supersedes_snapshot_id", models.UUIDField(blank=True, null=True)),
            ],
            options={"db_table": "hr13_title_material_snapshot"},
        ),
        migrations.AddConstraint(
            model_name="titlematerialsnapshot",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "material_no"),
                name="uq_hr13_material_tenant_no",
            ),
        ),
        migrations.AddIndex(
            model_name="titlematerialsnapshot",
            index=models.Index(
                fields=["tenant_id", "application_case_id", "status"],
                name="idx_hr13_material_case_status",
            ),
        ),
        migrations.AddIndex(
            model_name="titlematerialsnapshot",
            index=models.Index(
                fields=["tenant_id", "source_domain", "source_ref"],
                name="idx_hr13_material_source",
            ),
        ),
    ]
