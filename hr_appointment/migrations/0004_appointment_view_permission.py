from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("hr_appointment", "0003_effect_receipt")]

    operations = [
        migrations.AlterModelOptions(
            name="appointmentpolicyversion",
            options={
                "permissions": [("hr.appointment.view", "查看 HR14 岗位聘任工作区")],
            },
        ),
    ]
