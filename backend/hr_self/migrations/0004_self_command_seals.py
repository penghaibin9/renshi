from django.db import migrations

TRIGGERS = {'hr17_command_no_update': "CREATE TRIGGER `hr17_command_no_update` BEFORE UPDATE ON `hr17_self_command_receipt` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SELF_COMMAND_RECEIPT_IMMUTABLE'", 'hr17_command_no_delete': "CREATE TRIGGER `hr17_command_no_delete` BEFORE DELETE ON `hr17_self_command_receipt` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SELF_COMMAND_RECEIPT_IMMUTABLE'"}

def install(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        raise RuntimeError("MySQL-only migration; do not silently bypass database seals")
    for name, sql in TRIGGERS.items():
        schema_editor.execute("DROP TRIGGER IF EXISTS `" + name + "`")
        schema_editor.execute(sql)

def remove(apps, schema_editor):
    for name in TRIGGERS:
        schema_editor.execute("DROP TRIGGER IF EXISTS `" + name + "`")

class Migration(migrations.Migration):
    atomic = False
    dependencies = [('hr_self', '0003_self_commands'), ('hr_staff', '0021_self_submission_seals')]
    operations = [migrations.RunPython(install, remove)]
