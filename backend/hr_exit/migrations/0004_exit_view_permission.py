from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("hr_exit", "0003_exit_effect_saga")]

    operations = [
        migrations.AlterModelOptions(
            name="exitcase",
            options={
                "permissions": [("hr.exit.view", "查看 HR16 退休与离校工作区")],
            },
        ),
    ]
