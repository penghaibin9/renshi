import hashlib
import json

from django.db import migrations


EMPTY_SNAPSHOT_HASH = hashlib.sha256(
    json.dumps({}, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
TRIGGER = "hr_assessment_final_result_seal_insert"


def install_mysql_calculation_seal(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {TRIGGER}")
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS hr_assessment_final_result_no_update"
    )
    schema_editor.execute(
        "UPDATE hr_assessment_final_result "
        f"SET calculation_hash = '{EMPTY_SNAPSHOT_HASH}' "
        "WHERE calculation_hash = ''"
    )
    schema_editor.execute(
        """
        CREATE TRIGGER hr_assessment_final_result_no_update
        BEFORE UPDATE ON hr_assessment_final_result
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'HR12_FINAL_RESULT_IMMUTABLE: append a correction fact'
        """
    )
    schema_editor.execute(
        f"""
        CREATE TRIGGER {TRIGGER}
        BEFORE INSERT ON hr_assessment_final_result
        FOR EACH ROW
        BEGIN
            IF NEW.sealed_at IS NULL
               OR NEW.content_hash NOT REGEXP '^[0-9a-f]{{64}}$'
               OR NEW.calculation_hash NOT REGEXP '^[0-9a-f]{{64}}$' THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR12_FINAL_RESULT_SEAL_INVALID';
            END IF;
        END
        """
    )


def restore_mysql_result_seal(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute(f"DROP TRIGGER IF EXISTS {TRIGGER}")
    schema_editor.execute(
        f"""
        CREATE TRIGGER {TRIGGER}
        BEFORE INSERT ON hr_assessment_final_result
        FOR EACH ROW
        BEGIN
            IF NEW.sealed_at IS NULL
               OR NEW.content_hash NOT REGEXP '^[0-9a-f]{{64}}$' THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR12_FINAL_RESULT_IMMUTABLE: sealed_at and SHA-256 are required';
            END IF;
        END
        """
    )


class Migration(migrations.Migration):
    # The backfill is idempotent; trigger DDL is intentionally rerunnable.
    atomic = False

    dependencies = [
        ("hr_assessment", "0017_final_result_calculation_snapshot"),
    ]

    operations = [
        migrations.RunPython(
            install_mysql_calculation_seal,
            restore_mysql_result_seal,
            atomic=False,
        )
    ]
