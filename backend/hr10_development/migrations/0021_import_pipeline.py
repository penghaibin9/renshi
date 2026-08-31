from django.db import migrations, models

import hr10_development.legacy.import_job


class Migration(migrations.Migration):
    dependencies = [("hr10_development", "0020_state_convergence_06")]

    operations = [
        migrations.AddField(
            model_name="hrdevelopmentimportjob",
            name="checkpoint_row",
            field=models.PositiveIntegerField(default=0, verbose_name="解析断点行"),
        ),
        migrations.AddField(
            model_name="hrdevelopmentimportjob",
            name="idempotency_key",
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=64,
                null=True,
                unique=True,
                verbose_name="幂等键",
            ),
        ),
        migrations.AddField(
            model_name="hrdevelopmentimportjob",
            name="source_file",
            field=models.FileField(
                blank=True,
                max_length=512,
                upload_to=hr10_development.legacy.import_job.import_source_upload_to,
                verbose_name="受控源文件",
            ),
        ),
    ]
