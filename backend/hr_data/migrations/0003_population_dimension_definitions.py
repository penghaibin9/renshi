import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_data", "0002_data_view_permission")]

    operations = [
        migrations.AlterModelOptions(
            name="metricdefinitionversion",
            options={
                "permissions": [
                    ("hr.data.view", "查看 HR18 人事数据中心"),
                    ("hr.data.define", "维护 HR18 人口维度指标定义"),
                ],
            },
        ),
        migrations.CreateModel(
            name="PopulationDefinitionVersion",
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
                ("version_no", models.PositiveIntegerField(default=1)),
                ("status", models.CharField(db_index=True, default="DRAFT", max_length=32)),
                ("content_hash", models.CharField(blank=True, default="", max_length=64)),
                ("population_code", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True, default="")),
                ("root_domain", models.CharField(default="HR03", max_length=32)),
                ("predicate_json", models.JSONField(blank=True, default=dict)),
                ("source_domains", models.JSONField(blank=True, default=list)),
                ("as_of_required", models.BooleanField(default=True)),
            ],
            options={"db_table": "hr18_population_definition_version"},
        ),
        migrations.CreateModel(
            name="DimensionDefinitionVersion",
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
                ("version_no", models.PositiveIntegerField(default=1)),
                ("status", models.CharField(db_index=True, default="DRAFT", max_length=32)),
                ("content_hash", models.CharField(blank=True, default="", max_length=64)),
                ("dimension_code", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True, default="")),
                ("source_domain", models.CharField(max_length=32)),
                ("attribute_path", models.CharField(max_length=160)),
                ("value_type", models.CharField(max_length=32)),
                ("label_map_json", models.JSONField(blank=True, default=dict)),
                ("as_of_required", models.BooleanField(default=True)),
            ],
            options={"db_table": "hr18_dimension_definition_version"},
        ),
        migrations.AddConstraint(
            model_name="populationdefinitionversion",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "population_code", "version_no"),
                name="uq_hr18_population_code_ver",
            ),
        ),
        migrations.AddIndex(
            model_name="populationdefinitionversion",
            index=models.Index(
                fields=["tenant_id", "population_code", "status"],
                name="idx_hr18_population_status",
            ),
        ),
        migrations.AddConstraint(
            model_name="dimensiondefinitionversion",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "dimension_code", "version_no"),
                name="uq_hr18_dimension_code_ver",
            ),
        ),
        migrations.AddIndex(
            model_name="dimensiondefinitionversion",
            index=models.Index(
                fields=["tenant_id", "dimension_code", "status"],
                name="idx_hr18_dimension_status",
            ),
        ),
    ]
