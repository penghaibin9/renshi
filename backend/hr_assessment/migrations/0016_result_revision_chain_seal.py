from django.db import migrations


TRIGGER = "hr_assessment_result_revision_seal_insert"


def install_mysql_revision_chain_seal(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {TRIGGER}")
    schema_editor.execute(
        f"""
        CREATE TRIGGER {TRIGGER}
        BEFORE INSERT ON hr_assessment_result_revision
        FOR EACH ROW
        BEGIN
            DECLARE result_tenant BIGINT;
            DECLARE base_version INT;
            DECLARE current_version INT;
            SELECT MAX(tenant_id), MAX(result_version_no)
              INTO result_tenant, base_version
              FROM hr_assessment_final_result
             WHERE id = NEW.result_id;
            SELECT MAX(new_version)
              INTO current_version
              FROM hr_assessment_result_revision
             WHERE result_id = NEW.result_id;
            SET current_version = COALESCE(current_version, base_version);
            IF NEW.sealed_at IS NULL
               OR NEW.effective_at IS NULL
               OR NEW.content_hash NOT REGEXP '^[0-9a-f]{{64}}$'
               OR result_tenant IS NULL
               OR result_tenant <> NEW.tenant_id
               OR NEW.new_version <> NEW.previous_version + 1
               OR NEW.previous_version <> current_version THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR12_RESULT_REVISION_CHAIN_INVALID';
            END IF;
        END
        """
    )


def restore_mysql_shape_only_seal(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {TRIGGER}")
    schema_editor.execute(
        f"""
        CREATE TRIGGER {TRIGGER}
        BEFORE INSERT ON hr_assessment_result_revision
        FOR EACH ROW
        BEGIN
            IF NEW.sealed_at IS NULL
               OR NEW.content_hash NOT REGEXP '^[0-9a-f]{{64}}$' THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR12_RESULT_REVISION_IMMUTABLE: sealed_at and SHA-256 are required';
            END IF;
        END
        """
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("hr_assessment", "0015_result_application_ledger_seal"),
    ]

    operations = [
        migrations.RunPython(
            install_mysql_revision_chain_seal,
            restore_mysql_shape_only_seal,
            atomic=False,
        )
    ]
