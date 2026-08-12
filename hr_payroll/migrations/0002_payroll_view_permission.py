from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("hr_payroll", "0001_initial")]

    operations = [
        migrations.AlterModelOptions(
            name="payrollprofile",
            options={
                "permissions": [("hr.payroll.view", "查看 HR15 薪酬福利工作区")],
            },
        ),
    ]
