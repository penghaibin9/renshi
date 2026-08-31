from django.db import migrations


INDEX_NAME = "uniq_hr_external_active_exit_per_eng"
GUARD_COLUMN = "active_exit_guard"
ACTIVE_STATUSES = (
    "PLANNED",
    "UNDER_REVIEW",
    "READY_TO_EXIT",
    "EXITING",
    "CLEARANCE_PENDING",
)


def _table_name(apps):
    return apps.get_model("hr_external", "HrExternalExitCase")._meta.db_table


def _engagement_column(apps):
    # The legacy model names its ForeignKey ``engagement_id``, therefore the
    # physical attname/column is ``engagement_id_id``. Resolve it from migration
    # state instead of guessing the storage name.
    model = apps.get_model("hr_external", "HrExternalExitCase")
    return model._meta.get_field("engagement_id").column


def _assert_no_duplicates(apps, schema_editor):
    table = schema_editor.quote_name(_table_name(apps))
    engagement_column = schema_editor.quote_name(_engagement_column(apps))
    placeholders = ", ".join(["%s"] * len(ACTIVE_STATUSES))
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"""
                SELECT tenant_id, {engagement_column}, COUNT(*)
                FROM {table}
                WHERE status IN ({placeholders})
                GROUP BY tenant_id, {engagement_column}
                HAVING COUNT(*) > 1
                LIMIT 1
            """,
            ACTIVE_STATUSES,
        )
        duplicate = cursor.fetchone()
    if duplicate:
        tenant_id, engagement_id, count = duplicate
        raise RuntimeError(
            "Cannot install the active-exit uniqueness backstop: "
            f"tenant={tenant_id}, engagement={engagement_id} has {count} active cases. "
            "Resolve the duplicate exit cases before retrying this migration."
        )


def install_mysql_backstop(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    _assert_no_duplicates(apps, schema_editor)
    table = schema_editor.quote_name(_table_name(apps))
    engagement_column = schema_editor.quote_name(_engagement_column(apps))
    guard = schema_editor.quote_name(GUARD_COLUMN)
    index = schema_editor.quote_name(INDEX_NAME)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE {table} ADD COLUMN {guard} TINYINT "
            "GENERATED ALWAYS AS (CASE WHEN status IN ("
            "'PLANNED', 'UNDER_REVIEW', 'READY_TO_EXIT', 'EXITING', "
            "'CLEARANCE_PENDING') THEN 1 ELSE NULL END) STORED"
        )
        cursor.execute(
            f"CREATE UNIQUE INDEX {index} ON {table} "
            f"(tenant_id, {engagement_column}, {guard})"
        )


def uninstall_mysql_backstop(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    table = schema_editor.quote_name(_table_name(apps))
    guard = schema_editor.quote_name(GUARD_COLUMN)
    index = schema_editor.quote_name(INDEX_NAME)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP INDEX {index} ON {table}")
        cursor.execute(f"ALTER TABLE {table} DROP COLUMN {guard}")


class Migration(migrations.Migration):
    # MySQL DDL implicitly commits. Keep the migration restart behavior explicit.
    atomic = False

    dependencies = [
        ("hr_external", "0017_hrexternalpermissionmeta"),
    ]

    operations = [
        migrations.RunPython(install_mysql_backstop, uninstall_mysql_backstop),
    ]
