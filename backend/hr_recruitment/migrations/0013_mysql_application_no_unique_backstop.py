from django.db import migrations


INDEX_NAME = "uniq_hr_application_no_mysql"
GUARD_COLUMN = "application_no_guard"


def _model(apps):
    return apps.get_model("hr_recruitment", "HrJobApplication")


def _assert_no_duplicates(apps, schema_editor):
    table = schema_editor.quote_name(_model(apps)._meta.db_table)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"""
                SELECT tenant_id, application_no, COUNT(*)
                FROM {table}
                WHERE application_no <> ''
                GROUP BY tenant_id, application_no
                HAVING COUNT(*) > 1
                LIMIT 1
            """
        )
        duplicate = cursor.fetchone()
    if duplicate:
        tenant_id, application_no, count = duplicate
        raise RuntimeError(
            "Cannot install the application-number uniqueness backstop: "
            f"tenant={tenant_id}, application_no={application_no!r} has {count} rows. "
            "Resolve the duplicate applications before retrying this migration."
        )


def install_mysql_backstop(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    _assert_no_duplicates(apps, schema_editor)
    table = schema_editor.quote_name(_model(apps)._meta.db_table)
    guard = schema_editor.quote_name(GUARD_COLUMN)
    index = schema_editor.quote_name(INDEX_NAME)
    with schema_editor.connection.cursor() as cursor:
        # MySQL UNIQUE indexes permit multiple NULL values. Blank draft numbers
        # become NULL while every assigned number remains tenant-unique.
        cursor.execute(
            f"ALTER TABLE {table} ADD COLUMN {guard} VARCHAR(64) "
            "GENERATED ALWAYS AS (NULLIF(application_no, '')) STORED"
        )
        cursor.execute(
            f"CREATE UNIQUE INDEX {index} ON {table} (tenant_id, {guard})"
        )


def uninstall_mysql_backstop(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    table = schema_editor.quote_name(_model(apps)._meta.db_table)
    guard = schema_editor.quote_name(GUARD_COLUMN)
    index = schema_editor.quote_name(INDEX_NAME)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP INDEX {index} ON {table}")
        cursor.execute(f"ALTER TABLE {table} DROP COLUMN {guard}")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("hr_recruitment", "0012_alter_hrrecruitmentpermissionmeta_options_and_more"),
    ]

    operations = [
        migrations.RunPython(install_mysql_backstop, uninstall_mysql_backstop),
    ]
