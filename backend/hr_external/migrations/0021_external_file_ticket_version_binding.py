from django.db import migrations, models


def normalize_legacy_tickets(apps, schema_editor):
    ticket = apps.get_model("hr_external", "HrExternalFileTicket")
    ticket.objects.filter(purpose="").update(purpose="历史下载票据")
    ticket.objects.exclude(max_uses=1).update(max_uses=1)
    ticket.objects.filter(used_count__gt=1).update(used_count=1)


class Migration(migrations.Migration):
    dependencies = [("hr_external", "0020_academic_provisioning_outbox")]

    operations = [
        migrations.AddField(
            model_name="hrexternalfileticket",
            name="material_version_no",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.RunPython(normalize_legacy_tickets, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="hrexternalfileticket",
            constraint=models.CheckConstraint(
                condition=models.Q(purpose__gt=""),
                name="hex_file_ticket_purpose_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="hrexternalfileticket",
            constraint=models.CheckConstraint(
                condition=models.Q(max_uses=1),
                name="hex_file_ticket_single_use",
            ),
        ),
        migrations.AddConstraint(
            model_name="hrexternalfileticket",
            constraint=models.CheckConstraint(
                condition=models.Q(used_count__lte=1),
                name="hex_file_ticket_used_lte_one",
            ),
        ),
        migrations.AddConstraint(
            model_name="hrexternalfileticket",
            constraint=models.CheckConstraint(
                condition=models.Q(material_version_no__gte=1),
                name="hex_file_ticket_version_gte_one",
            ),
        ),
    ]
