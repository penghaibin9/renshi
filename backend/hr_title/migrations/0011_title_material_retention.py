from django.db import migrations


def install_mysql_material_retention(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS hr13_title_material_no_delete")
    schema_editor.execute(
        """
        CREATE TRIGGER hr13_title_material_no_delete
        BEFORE DELETE ON hr13_title_material_snapshot
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'TITLE_MATERIAL_RETENTION_REQUIRED: review evidence cannot be deleted'
        """
    )


def drop_mysql_material_retention(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS hr13_title_material_no_delete")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("hr_title", "0010_title_result_authority_boundary")]

    operations = [
        migrations.RunPython(
            install_mysql_material_retention,
            drop_mysql_material_retention,
        ),
    ]
