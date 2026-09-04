from django.db import migrations, models
from django.db.models.functions import Length


def assert_titles_fit_mysql_unique_index(apps, schema_editor):
    MailAutomation = apps.get_model("horilla_automations", "MailAutomation")
    too_long = (
        MailAutomation.objects.annotate(title_length=Length("title"))
        .filter(title_length__gt=255)
        .values_list("title", flat=True)
        .first()
    )
    if too_long is not None:
        raise RuntimeError(
            "Cannot reduce MailAutomation.title to 255 characters: "
            f"an existing title contains {len(too_long)} characters."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("horilla_automations", "0003_alter_mailautomation_mail_details_and_more"),
    ]

    operations = [
        migrations.RunPython(
            assert_titles_fit_mysql_unique_index,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="mailautomation",
            name="title",
            field=models.CharField(max_length=255, unique=True),
        ),
    ]
