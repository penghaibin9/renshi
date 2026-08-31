from django.db import migrations, models


UPDATE_TRIGGER = "trg_hr15_input_snapshot_no_update"
DELETE_TRIGGER = "trg_hr15_input_snapshot_no_delete"
TABLE = "hr15_payroll_input_snapshot"


def create_snapshot_triggers(apps, schema_editor):
    del apps
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute(f"DROP TRIGGER IF EXISTS `{UPDATE_TRIGGER}`")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS `{DELETE_TRIGGER}`")
    schema_editor.execute(
        f"""
        CREATE TRIGGER `{UPDATE_TRIGGER}`
        BEFORE UPDATE ON `{TABLE}`
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'PAYROLL_INPUT_IMMUTABLE'
        """
    )
    schema_editor.execute(
        f"""
        CREATE TRIGGER `{DELETE_TRIGGER}`
        BEFORE DELETE ON `{TABLE}`
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'PAYROLL_INPUT_IMMUTABLE'
        """
    )


def drop_snapshot_triggers(apps, schema_editor):
    del apps
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute(f"DROP TRIGGER IF EXISTS `{UPDATE_TRIGGER}`")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS `{DELETE_TRIGGER}`")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("hr_payroll", "0009_hrpayrolllegacytakeoverpermissionmeta_and_more")]

    operations = [
        migrations.AddField(
            model_name="payrollinputsnapshot",
            name="snapshot_version",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.RunPython(
            create_snapshot_triggers,
            reverse_code=drop_snapshot_triggers,
        ),
    ]
