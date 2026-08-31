from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("hr_self", "0001_initial")]

    operations = [
        migrations.AlterModelOptions(
            name="selfservicecatalogitem",
            options={
                "permissions": [("hr.self.view", "访问 HR17 教职工本人服务")],
            },
        ),
    ]
