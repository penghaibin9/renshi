from django.db import migrations


SET_TABLE = "hr_assessment_provider_snapshot_set"
ITEM_TABLE = "hr_assessment_provider_snapshot_item"


def install_mysql_membership_seal(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    schema_editor.execute(f"DROP TRIGGER IF EXISTS {SET_TABLE}_no_update")
    schema_editor.execute(
        f"""
        CREATE TRIGGER {SET_TABLE}_no_update
        BEFORE UPDATE ON {SET_TABLE}
        FOR EACH ROW
        BEGIN
            IF OLD.status <> 'CAPTURING'
               OR NEW.status NOT IN ('READY', 'BLOCKED')
               OR OLD.captured_at IS NOT NULL
               OR NEW.captured_at IS NULL
               OR NOT (OLD.tenant_id <=> NEW.tenant_id)
               OR NOT (OLD.case_id <=> NEW.case_id)
               OR NOT (OLD.as_of <=> NEW.as_of)
               OR NOT (OLD.authority_json <=> NEW.authority_json)
               OR NOT (OLD.required_providers_json <=> NEW.required_providers_json)
               OR NOT (OLD.provider_status_json <=> NEW.provider_status_json)
               OR NOT (OLD.content_hash <=> NEW.content_hash)
               OR NOT (OLD.request_id <=> NEW.request_id) THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR12_PROVIDER_SNAPSHOT_IMMUTABLE';
            END IF;
        END
        """
    )
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS hr_assessment_provider_snapshot_set_seal_insert"
    )
    schema_editor.execute(
        f"""
        CREATE TRIGGER hr_assessment_provider_snapshot_set_seal_insert
        BEFORE INSERT ON {SET_TABLE}
        FOR EACH ROW
        BEGIN
            IF NEW.content_hash NOT REGEXP '^[0-9a-f]{{64}}$'
               OR NEW.captured_at IS NOT NULL
               OR NEW.status <> 'CAPTURING' THEN
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
               OR parent_case <> NEW.case_id
               OR parent_status <> 'CAPTURING' THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR12_PROVIDER_SNAPSHOT_ITEM_INVALID';
            END IF;
        END
        """
    )


def restore_previous_mysql_seal(apps, schema_editor):
    from importlib import import_module

    previous = import_module(
        "hr_assessment.migrations.0014_provider_snapshot_seals"
    )
    previous.install_mysql_snapshot_seals(apps, schema_editor)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("hr_assessment", "0018_final_result_calculation_seal"),
    ]

    operations = [
        migrations.RunPython(
            install_mysql_membership_seal,
            restore_previous_mysql_seal,
            atomic=False,
        )
    ]
