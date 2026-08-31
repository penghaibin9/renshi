from django.db import migrations


def add_mysql_backstops(apps, schema_editor):
    """Materialize conditional uniqueness on MySQL via generated columns.

    Django's conditional UniqueConstraint is not emitted as a partial unique
    index on MySQL. These generated keys preserve NULL for rows outside the
    guarded condition, so MySQL's multiple-NULL unique semantics implement the
    intended production invariant without weakening historical rows.
    """
    if schema_editor.connection.vendor != "mysql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            ALTER TABLE hr_staff_hrstaffassignment
              ADD COLUMN open_primary_rel_key CHAR(32)
              GENERATED ALWAYS AS (
                CASE
                  WHEN assignment_type = 'PRIMARY' AND effective_to IS NULL
                  THEN employment_relationship_id_id
                  ELSE NULL
                END
              ) STORED
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX uniq_hr_assignment_open_primary_mysql
            ON hr_staff_hrstaffassignment (tenant_id, open_primary_rel_key)
            """
        )

        cursor.execute(
            """
            ALTER TABLE hr_staff_hrpersonidentitydocument
              ADD COLUMN nonempty_fingerprint_key CHAR(64)
              GENERATED ALWAYS AS (NULLIF(document_number_fingerprint, '')) STORED
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX uniq_hr_identity_fingerprint_mysql
            ON hr_staff_hrpersonidentitydocument (tenant_id, nonempty_fingerprint_key)
            """
        )


def remove_mysql_backstops(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP INDEX uniq_hr_identity_fingerprint_mysql "
            "ON hr_staff_hrpersonidentitydocument"
        )
        cursor.execute(
            "ALTER TABLE hr_staff_hrpersonidentitydocument "
            "DROP COLUMN nonempty_fingerprint_key"
        )
        cursor.execute(
            "DROP INDEX uniq_hr_assignment_open_primary_mysql "
            "ON hr_staff_hrstaffassignment"
        )
        cursor.execute(
            "ALTER TABLE hr_staff_hrstaffassignment "
            "DROP COLUMN open_primary_rel_key"
        )


class Migration(migrations.Migration):
    # MySQL DDL performs implicit commits; keep generated-column/index setup
    # outside Django's migration transaction in both forward and reverse paths.
    atomic = False

    dependencies = [("hr_staff", "0012_hrpersonmergecase_hrpersonmergealias_and_more")]

    operations = [
        migrations.RunPython(add_mysql_backstops, remove_mysql_backstops),
    ]
