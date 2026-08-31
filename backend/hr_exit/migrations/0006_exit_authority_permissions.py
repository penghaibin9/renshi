from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("hr_exit", "0005_exit_handover_checklist"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="exitcase",
            options={
                "permissions": [
                    ("hr.exit.view", "查看 HR16 退休与离校工作区"),
                    ("hr.exit.manage", "办理 HR16 退休与离校流程"),
                    ("hr.exit.handover", "维护 HR16 离校交接清单"),
                    ("hr.exit.effect", "执行 HR16 正式离校就业关系生效"),
                ],
            },
        ),
    ]
