from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("hr_payroll", "0002_payroll_view_permission")]

    operations = [
        migrations.AlterModelOptions(
            name="payrollprofile",
            options={
                "permissions": [
                    ("hr.payroll.view", "查看 HR15 薪酬福利工作区"),
                    ("hr.payroll.adjust", "执行 HR15 薪资追溯调整"),
                ],
            },
        ),
    ]
