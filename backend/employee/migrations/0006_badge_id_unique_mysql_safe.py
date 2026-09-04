from django.db import migrations, models


def assert_no_duplicate_badges(apps, schema_editor):
    Employee = apps.get_model("employee", "Employee")
    duplicate = (
        Employee.objects.exclude(badge_id__isnull=True)
        .values("badge_id")
        .annotate(row_count=models.Count("id"))
        .filter(row_count__gt=1)
        .order_by("badge_id")
        .first()
    )
    if duplicate:
        raise RuntimeError(
            "Cannot enforce employee badge uniqueness: "
            f"badge_id={duplicate['badge_id']!r} has {duplicate['row_count']} rows. "
            "Resolve the duplicate employee badges before retrying this migration."
        )


class Migration(migrations.Migration):
    dependencies = [("employee", "0005_alter_employee_phone_and_more")]

    operations = [
        migrations.RunPython(assert_no_duplicate_badges, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="employee",
            name="unique_badge_id",
        ),
        migrations.AddConstraint(
            model_name="employee",
            constraint=models.UniqueConstraint(
                fields=("badge_id",),
                name="unique_badge_id",
            ),
        ),
    ]
