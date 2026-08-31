from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hr_external", "0014_shorten_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="hrexternalprojectionstate",
            name="version",
            field=models.BigIntegerField(default=1),
        ),
        migrations.AddConstraint(
            model_name="hrexternalprojectionstate",
            constraint=models.CheckConstraint(
                condition=models.Q(("version__gte", 1)),
                name="hex_projection_version_gte_1",
            ),
        ),
    ]
