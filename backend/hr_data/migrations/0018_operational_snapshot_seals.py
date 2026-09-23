from django.db import migrations

TRIGGERS = {'hr18_observation_no_update': "CREATE TRIGGER `hr18_observation_no_update` BEFORE UPDATE ON `hr18_operational_snapshot` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OBSERVATION_IMMUTABLE'", 'hr18_observation_no_delete': "CREATE TRIGGER `hr18_observation_no_delete` BEFORE DELETE ON `hr18_operational_snapshot` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OBSERVATION_IMMUTABLE'"}

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
    dependencies = [('hr_data', '0017_operational_snapshot')]
    operations = [migrations.RunPython(install, remove)]
