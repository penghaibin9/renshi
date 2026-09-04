import hashlib

from django.db import migrations, models


PREFIX = "sha256$"


def digest(value, namespace):
    return PREFIX + hashlib.sha256(
        b"renshi:bearer-token:v1:"
        + namespace.encode("utf-8")
        + b":"
        + value.encode("utf-8")
    ).hexdigest()


def hash_existing_tokens(apps, schema_editor):
    ticket_model = apps.get_model("hr_staff", "HrMaterialDownloadTicket")
    for instance in ticket_model.objects.all().only("pk", "token").iterator():
        value = str(instance.token or "")
        if value and not (value.startswith(PREFIX) and len(value) == 71):
            ticket_model.objects.filter(pk=instance.pk).update(
                token=digest(value, "hr03-material-download")
            )

    export_model = apps.get_model("hr_staff", "HrExportJob")
    for instance in export_model.objects.all().only("pk", "download_token").iterator():
        value = str(instance.download_token or "")
        if value and not (value.startswith(PREFIX) and len(value) == 71):
            export_model.objects.filter(pk=instance.pk).update(
                download_token=digest(value, "hr03-export-download")
            )


class Migration(migrations.Migration):
    dependencies = [("hr_staff", "0017_hrstaffassignment_location_code")]

    operations = [
        migrations.AlterField(
            model_name="hrmaterialdownloadticket",
            name="token",
            field=models.CharField(db_index=True, max_length=71, unique=True),
        ),
        migrations.AlterField(
            model_name="hrexportjob",
            name="download_token",
            field=models.CharField(blank=True, default="", max_length=71),
        ),
        migrations.RunPython(hash_existing_tokens, migrations.RunPython.noop),
    ]
