"""Repair the HR12 provider snapshot item trigger for mixed MySQL collations.

Migration 0014 declared ``parent_case`` without an explicit collation.  On
MySQL 8.4 that local variable inherits the server default
``utf8mb4_0900_ai_ci`` while Django's UUID ``case_id`` column uses
``utf8mb4_unicode_ci``.  Comparing the two text values therefore fails before
the trigger can enforce its immutable-fact boundary.

Do not edit the already-applied 0014 migration.  Recreate only the affected
trigger and compare UUID text as binary bytes so the check is independent of
server/database collation defaults and remains exact.
"""

from django.db import migrations


TRIGGER_NAME = "hr_assessment_provider_snapshot_item_seal_insert"

DROP_TRIGGER_SQL = f"DROP TRIGGER IF EXISTS {TRIGGER_NAME}"

CREATE_TRIGGER_SQL = f"""
CREATE TRIGGER {TRIGGER_NAME}
BEFORE INSERT ON hr_assessment_provider_snapshot_item
FOR EACH ROW
BEGIN
    DECLARE parent_tenant BIGINT;
    DECLARE parent_case CHAR(32);
    SELECT MAX(tenant_id), MAX(case_id)
      INTO parent_tenant, parent_case
      FROM hr_assessment_provider_snapshot_set
     WHERE id = NEW.snapshot_set_id;
    IF NEW.snapshot_hash NOT REGEXP '^[0-9a-f]{{64}}$'
       OR parent_tenant IS NULL
       OR parent_tenant <> NEW.tenant_id
       OR CAST(parent_case AS BINARY) <> CAST(NEW.case_id AS BINARY) THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'HR12_PROVIDER_SNAPSHOT_ITEM_INVALID';
    END IF;
END
"""


def recreate_collation_safe_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(DROP_TRIGGER_SQL)
        cursor.execute(CREATE_TRIGGER_SQL)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("hr_assessment", "0027_document_access_audit"),
    ]

    operations = [
        migrations.RunPython(
            recreate_collation_safe_trigger,
            reverse_code=recreate_collation_safe_trigger,
        )
    ]
