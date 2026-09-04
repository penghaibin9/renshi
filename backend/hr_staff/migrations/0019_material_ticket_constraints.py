from django.db import migrations, models


def normalize_legacy_tickets(apps, schema_editor):
    ticket = apps.get_model("hr_staff", "HrMaterialDownloadTicket")
    ticket.objects.filter(purpose="").update(purpose="历史材料下载")
    ticket.objects.exclude(max_uses=1).update(max_uses=1)
    ticket.objects.filter(uses__gt=1).update(uses=1)


class Migration(migrations.Migration):
    dependencies = [("hr_staff", "0018_hash_download_tokens")]

    operations = [
        migrations.RunPython(normalize_legacy_tickets, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="hrmaterialdownloadticket",
            constraint=models.CheckConstraint(
                condition=models.Q(purpose__gt=""),
                name="hr03_ticket_purpose_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="hrmaterialdownloadticket",
            constraint=models.CheckConstraint(
                condition=models.Q(max_uses=1),
                name="hr03_ticket_single_use",
            ),
        ),
        migrations.AddConstraint(
            model_name="hrmaterialdownloadticket",
            constraint=models.CheckConstraint(
                condition=models.Q(uses__lte=1),
                name="hr03_ticket_uses_lte_one",
            ),
        ),
    ]
