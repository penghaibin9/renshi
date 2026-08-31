from django.db import migrations


def create_mysql_ranking_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TRIGGER IF EXISTS hr14_ranking_reject_update")
        cursor.execute("DROP TRIGGER IF EXISTS hr14_ranking_reject_delete")
        cursor.execute(
            """
            CREATE TRIGGER hr14_ranking_reject_update
            BEFORE UPDATE ON hr14_appointment_ranking_result
            FOR EACH ROW
            BEGIN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'HR14_RANKING_FACT_APPEND_ONLY_UPDATE';
            END
            """
        )
        cursor.execute(
            """
            CREATE TRIGGER hr14_ranking_reject_delete
            BEFORE DELETE ON hr14_appointment_ranking_result
            FOR EACH ROW
            BEGIN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'HR14_RANKING_FACT_APPEND_ONLY_DELETE';
            END
            """
        )


def drop_mysql_ranking_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TRIGGER IF EXISTS hr14_ranking_reject_update")
        cursor.execute("DROP TRIGGER IF EXISTS hr14_ranking_reject_delete")


class Migration(migrations.Migration):
    # MySQL trigger DDL performs implicit commits.
    atomic = False

    dependencies = [("hr_appointment", "0015_formal_appointment_fact_seal")]

    operations = [
        migrations.RunPython(
            create_mysql_ranking_triggers,
            drop_mysql_ranking_triggers,
        )
    ]
