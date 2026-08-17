from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_data", "0006_submission_async_dispatch"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="metricdefinitionversion",
            options={
                "permissions": [
                    ("hr.data.view", "查看 HR18 人事数据中心"),
                    ("hr.data.define", "维护 HR18 人口维度指标定义"),
                    ("hr.data.asof", "执行 HR18 历史时点重建"),
                    ("hr.data.quality", "执行 HR18 数据质量治理"),
                ]
            },
        ),
        migrations.AddField(
            model_name="asofevidencesnapshot",
            name="definition_kind",
            field=models.CharField(
                choices=[
                    ("UNKNOWN", "Legacy / unknown"),
                    ("POPULATION", "Population definition"),
                    ("DIMENSION", "Dimension definition"),
                    ("METRIC", "Metric definition"),
                ],
                db_index=True,
                default="UNKNOWN",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="asofevidencesnapshot",
            name="provider_evidence_hashes_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="submissionsnapshot",
            name="definition_kind",
            field=models.CharField(
                choices=[
                    ("UNKNOWN", "Legacy / unknown"),
                    ("POPULATION", "Population definition"),
                    ("DIMENSION", "Dimension definition"),
                    ("METRIC", "Metric definition"),
                ],
                db_index=True,
                default="UNKNOWN",
                max_length=16,
            ),
        ),
        migrations.RemoveIndex(
            model_name="asofevidencesnapshot",
            name="idx_hr18_asof_def_status",
        ),
        migrations.AddIndex(
            model_name="asofevidencesnapshot",
            index=models.Index(
                fields=[
                    "tenant_id",
                    "definition_kind",
                    "definition_code",
                    "as_of_date",
                    "status",
                ],
                name="idx_hr18_asof_def_status",
            ),
        ),
        migrations.RemoveIndex(
            model_name="submissionsnapshot",
            name="idx_hr18_submission_def_status",
        ),
        migrations.AddIndex(
            model_name="submissionsnapshot",
            index=models.Index(
                fields=["tenant_id", "definition_kind", "definition_code", "status"],
                name="idx_hr18_submission_def_status",
            ),
        ),
    ]
