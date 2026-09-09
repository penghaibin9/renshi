"""Repair the HR12 provider snapshot item seals for mixed MySQL collations.

Migration 0019 inherited the item immutability triggers from migration 0014 and
replaced the item insert trigger with a membership-aware definition.  The
insert trigger declared ``parent_case`` without an explicit collation.  On
MySQL 8.4 that local variable can inherit ``utf8mb4_0900_ai_ci`` while
Django's UUID ``case_id`` column uses ``utf8mb4_unicode_ci``.  A plain text
comparison then fails before the trigger can enforce the immutable-fact
boundary.

Do not edit already-applied historical migrations.  Recreate the complete
item trigger set here, retain the sealed-membership check introduced by 0019,
and compare UUID text as binary bytes so enforcement is independent of server
collation defaults.
"""

from importlib import import_module

from django.db import migrations


ITEM_TABLE = "hr_assessment_provider_snapshot_item"
SET_TABLE = "hr_assessment_provider_snapshot_set"


def install_collation_safe_snapshot_item_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    schema_editor.execute(f"DROP TRIGGER IF EXISTS {ITEM_TABLE}_no_update")
    schema_editor.execute(
        f"""
        CREATE TRIGGER {ITEM_TABLE}_no_update
        BEFORE UPDATE ON {ITEM_TABLE}
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'HR12_PROVIDER_SNAPSHOT_IMMUTABLE'
        """
    )
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {ITEM_TABLE}_no_delete")
    schema_editor.execute(
        f"""
        CREATE TRIGGER {ITEM_TABLE}_no_delete
        BEFORE DELETE ON {ITEM_TABLE}
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'HR12_PROVIDER_SNAPSHOT_IMMUTABLE'
        """
    )
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS "
        "hr_assessment_provider_snapshot_item_seal_insert"
    )
    schema_editor.execute(
        f"""
        CREATE TRIGGER hr_assessment_provider_snapshot_item_seal_insert
        BEFORE INSERT ON {ITEM_TABLE}
        FOR EACH ROW
        BEGIN
            DECLARE parent_tenant BIGINT;
            DECLARE parent_case CHAR(32);
            DECLARE parent_status VARCHAR(30);
            SELECT MAX(tenant_id), MAX(case_id), MAX(status)
              INTO parent_tenant, parent_case, parent_status
              FROM {SET_TABLE}
             WHERE id = NEW.snapshot_set_id;
            IF NEW.snapshot_hash NOT REGEXP '^[0-9a-f]{{64}}$'
               OR parent_tenant IS NULL
               OR parent_tenant <> NEW.tenant_id
               OR CAST(parent_case AS BINARY) <> CAST(NEW.case_id AS BINARY)
               OR parent_status <> 'CAPTURING' THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR12_PROVIDER_SNAPSHOT_ITEM_INVALID';
            END IF;
        END
        """
    )


def restore_previous_snapshot_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    base_seals = import_module(
        "hr_assessment.migrations.0014_provider_snapshot_seals"
    )
    membership_seals = import_module(
        "hr_assessment.migrations.0019_provider_snapshot_membership_seal"
    )
    base_seals.install_mysql_snapshot_seals(apps, schema_editor)
    membership_seals.install_mysql_membership_seal(apps, schema_editor)


class Migration(migrations.Migration):
    # MySQL trigger DDL implicitly commits and must not run in an atomic block.
    atomic = False

    dependencies = [
        ("hr_assessment", "0027_document_access_audit"),
    ]

    operations = [
        migrations.RunPython(
            install_collation_safe_snapshot_item_seals,
            restore_previous_snapshot_seals,
            atomic=False,
        )
    ]
