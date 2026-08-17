from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("hr_appointment", "0010_ranking_terminal_case_statuses"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="appointmentpolicyversion",
            options={
                "permissions": [
                    ("hr.appointment.view", "查看 HR14 岗位聘任工作区"),
                    ("hr.appointment.review", "执行 HR14 评议排序"),
                    ("hr.appointment.publicity", "维护 HR14 拟聘公示与异议"),
                    ("hr.appointment.effect", "执行 HR14 正式聘任生效"),
                ],
            },
        ),
    ]
