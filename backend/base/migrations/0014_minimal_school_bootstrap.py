from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import horilla.models


def seed_lock(apps, schema_editor):
    apps.get_model("base", "SchoolBootstrapState").objects.using(schema_editor.connection.alias).get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [
        ("base", "0013_protect_email_audit_logs"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AlterField(model_name="company", name="icon", field=models.FileField(upload_to=horilla.models.upload_path, null=True, blank=True)),
        migrations.AlterField(model_name="company", name="address", field=models.TextField(max_length=255, blank=True, default="")),
        *[migrations.AlterField(model_name="company", name=name, field=models.CharField(max_length=length, blank=True, default=""))
          for name, length in (("country",50),("state",50),("city",50),("zip",20))],
        migrations.CreateModel(
            name="SchoolBootstrapState",
            fields=[
                ("id", models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False, serialize=False)),
                ("completed_at", models.DateTimeField(null=True, blank=True)),
                ("company", models.ForeignKey(to="base.company", null=True, blank=True, on_delete=django.db.models.deletion.PROTECT)),
                ("administrator", models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=django.db.models.deletion.PROTECT)),
            ],
            options={"constraints": [models.CheckConstraint(condition=models.Q(id=1), name="single_school_bootstrap_state")]},
        ),
        migrations.RunPython(seed_lock, migrations.RunPython.noop),
    ]
