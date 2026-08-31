from django.db import migrations


def add_mysql_active_application_backstop(apps, schema_editor):
    """Enforce one active application per tenant/candidate/position on MySQL.

    MySQL doesn't provide partial unique indexes for Django's conditional
    UniqueConstraint. A generated guard is 1 for active rows and NULL for
    inactive rows; the unique index therefore blocks concurrent duplicate
    active applications while allowing historical inactive applications.
    """
    if schema_editor.connection.vendor != "mysql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            ALTER TABLE hr_recruitment_hrjobapplication
              ADD COLUMN active_application_guard TINYINT
              GENERATED ALWAYS AS (
                CASE WHEN is_active = 1 THEN 1 ELSE NULL END
              ) STORED
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX uniq_hr_application_active_mysql
            ON hr_recruitment_hrjobapplication (
              tenant_id,
              candidate_id_id,
              recruitment_position_id_id,
              active_application_guard
            )
            """
        )


def remove_mysql_active_application_backstop(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP INDEX uniq_hr_application_active_mysql "
            "ON hr_recruitment_hrjobapplication"
        )
        cursor.execute(
            "ALTER TABLE hr_recruitment_hrjobapplication "
            "DROP COLUMN active_application_guard"
        )


class Migration(migrations.Migration):
    # ALTER TABLE / CREATE INDEX implicitly commit on MySQL; reverse DDL has
    # the same requirement.
    atomic = False

    dependencies = [("hr_recruitment", "0009_hrassessmentparticipant")]

    operations = [
        migrations.RunPython(
            add_mysql_active_application_backstop,
            remove_mysql_active_application_backstop,
        ),
    ]
