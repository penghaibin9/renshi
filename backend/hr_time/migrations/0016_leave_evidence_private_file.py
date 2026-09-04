from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_time", "0015_leave_calculation_snapshot")]

    operations = [
        migrations.AddField(
            model_name="hrleaveevidence",
            name="storage_key",
            field=models.CharField(
                default="",
                help_text="仅供服务端鉴权下载使用，不得作为公开 URL 返回。",
                max_length=512,
                verbose_name="私有存储键",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="hrleaveevidence",
            name="original_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="hrleaveevidence",
            name="content_type",
            field=models.CharField(blank=True, default="", max_length=127),
        ),
        migrations.AddField(
            model_name="hrleaveevidence",
            name="file_size",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="hrleaveevidence",
            name="sha256",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddConstraint(
            model_name="hrleaveevidence",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "document_id"),
                name="uniq_hr11_leave_evidence_doc",
            ),
        ),
    ]
