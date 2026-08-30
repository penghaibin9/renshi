from django.db import migrations


TABLES = (
    "hr_assessment_provider_snapshot_set",
    "hr_assessment_provider_snapshot_item",
)


def install_mysql_snapshot_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    for table in TABLES:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
        schema_editor.execute(
            f"""
            CREATE TRIGGER {table}_no_update
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR12_PROVIDER_SNAPSHOT_IMMUTABLE'
            """
        )
        schema_editor.execute(
            f"""
            CREATE TRIGGER {table}_no_delete
            BEFORE DELETE ON {table}
            FOR EACH ROW
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'HR12_PROVIDER_SNAPSHOT_IMMUTABLE'
            """
        )

    schema_editor.execute(
        "DROP TRIGGER IF EXISTS hr_assessment_provider_snapshot_set_seal_insert"
    )
    schema_editor.execute(
        """
        CREATE TRIGGER hr_assessment_provider_snapshot_set_seal_insert
        BEFORE INSERT ON hr_assessment_provider_snapshot_set
        FOR EACH ROW
        BEGIN
            IF NEW.content_hash NOT REGEXP '^[0-9a-f]{64}$'
               OR NEW.captured_at IS NULL
               OR NEW.status NOT IN ('READY', 'BLOCKED') THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR12_PROVIDER_SNAPSHOT_SET_INVALID';
            END IF;
        END
        """
    )
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS hr_assessment_provider_snapshot_item_seal_insert"
    )
    schema_editor.execute(
        """
        CREATE TRIGGER hr_assessment_provider_snapshot_item_seal_insert
        BEFORE INSERT ON hr_assessment_provider_snapshot_item
        FOR EACH ROW
        BEGIN
            DECLARE parent_tenant BIGINT;
            DECLARE parent_case CHAR(32);
            SELECT MAX(tenant_id), MAX(case_id)
              INTO parent_tenant, parent_case
              FROM hr_assessment_provider_snapshot_set
             WHERE id = NEW.snapshot_set_id;
            IF NEW.snapshot_hash NOT REGEXP '^[0-9a-f]{64}$'
               OR parent_tenant IS NULL
               OR parent_tenant <> NEW.tenant_id
               OR parent_case <> NEW.case_id THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR12_PROVIDER_SNAPSHOT_ITEM_INVALID';
            END IF;
        END
        """
    )


def remove_mysql_snapshot_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    for table in TABLES:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS hr_assessment_provider_snapshot_set_seal_insert"
    )
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS hr_assessment_provider_snapshot_item_seal_insert"
    )


class Migration(migrations.Migration):
    # MySQL trigger DDL implicitly commits and cannot be rolled back safely.
    atomic = False

    dependencies = [("hr_assessment", "0013_hrassessmentpermissionmeta")]

    operations = [
        migrations.RunPython(
            install_mysql_snapshot_seals,
            remove_mysql_snapshot_seals,
            atomic=False,
        )
    ]
