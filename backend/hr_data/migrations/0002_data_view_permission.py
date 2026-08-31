from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("hr_data", "0001_initial")]

    operations = [
        migrations.AlterModelOptions(
            name="metricdefinitionversion",
            options={
                "permissions": [("hr.data.view", "查看 HR18 人事数据中心")],
            },
        ),
    ]
