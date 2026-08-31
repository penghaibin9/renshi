from django.db import migrations, models


TABLE = "hr_assessment_result_application_ledger"


def install_mysql_ledger_seal(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {TABLE}_seal_insert")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {TABLE}_no_update")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {TABLE}_no_delete")
    schema_editor.execute(
        f"""
        CREATE TRIGGER {TABLE}_seal_insert
        BEFORE INSERT ON {TABLE}
        FOR EACH ROW
        BEGIN
            DECLARE result_tenant BIGINT;
            SELECT MAX(tenant_id) INTO result_tenant
              FROM hr_assessment_final_result
             WHERE id = NEW.result_id;
            IF result_tenant IS NULL
               OR result_tenant <> NEW.tenant_id
               OR NEW.consumer_object_id IS NULL
               OR NEW.consumer_domain = ''
               OR NEW.purpose = ''
               OR NEW.result_version < 1 THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR12_RESULT_APPLICATION_LEDGER_INVALID';
            END IF;
        END
        """
    )
    schema_editor.execute(
        f"""
        CREATE TRIGGER {TABLE}_no_update
        BEFORE UPDATE ON {TABLE}
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'HR12_RESULT_APPLICATION_LEDGER_IMMUTABLE'
        """
    )
    schema_editor.execute(
        f"""
        CREATE TRIGGER {TABLE}_no_delete
        BEFORE DELETE ON {TABLE}
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'HR12_RESULT_APPLICATION_LEDGER_IMMUTABLE'
        """
    )


def remove_mysql_ledger_seal(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {TABLE}_seal_insert")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {TABLE}_no_update")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {TABLE}_no_delete")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("hr_assessment", "0014_provider_snapshot_seals")]

    operations = [
        migrations.AddConstraint(
            model_name="hrresultapplicationledger",
            constraint=models.UniqueConstraint(
                fields=(
                    "tenant_id",
                    "result",
                    "consumer_domain",
                    "consumer_object_id",
                    "purpose",
                    "result_version",
                ),
                name="hr12_result_application_idempotency_uq",
            ),
        ),
        migrations.RunPython(
            install_mysql_ledger_seal,
            remove_mysql_ledger_seal,
            atomic=False,
        ),
    ]
