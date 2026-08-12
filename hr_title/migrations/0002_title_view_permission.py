from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("hr_title", "0001_initial")]

    operations = [
        migrations.AlterModelOptions(
            name="titlepolicyversion",
            options={
                "permissions": [("hr.title.view", "查看 HR13 职称评审工作区")],
            },
        ),
    ]
