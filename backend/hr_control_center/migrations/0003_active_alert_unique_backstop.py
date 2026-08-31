from django.db import migrations, models
from django.db.models import Q


INDEX_NAME = "uniq_hr_alert_open_dedupe"
GUARD_COLUMN = "active_dedupe_guard"
ACTIVE_STATUSES = ("OPEN", "ACKNOWLEDGED", "SNOOZED")


def _table_name(apps):
    return apps.get_model("hr_control_center", "HrAlertInstance")._meta.db_table


def _assert_no_active_duplicates(apps, schema_editor):
    table = schema_editor.quote_name(_table_name(apps))
    placeholders = ", ".join(["%s"] * len(ACTIVE_STATUSES))
    sql = f"""
        SELECT tenant_id, dedupe_key, COUNT(*)
        FROM {table}
        WHERE status IN ({placeholders})
        GROUP BY tenant_id, dedupe_key
        HAVING COUNT(*) > 1
        LIMIT 1
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(sql, ACTIVE_STATUSES)
        duplicate = cursor.fetchone()
    if duplicate:
        tenant_id, dedupe_key, count = duplicate
        raise RuntimeError(
            "Cannot install the active-alert uniqueness backstop: "
            f"tenant={tenant_id}, dedupe_key={dedupe_key!r} has {count} active rows. "
            "Resolve the duplicate alerts before retrying this migration."
        )


def install_active_alert_backstop(apps, schema_editor):
    _assert_no_active_duplicates(apps, schema_editor)
    vendor = schema_editor.connection.vendor
    table = schema_editor.quote_name(_table_name(apps))
    index = schema_editor.quote_name(INDEX_NAME)

    with schema_editor.connection.cursor() as cursor:
        if vendor == "mysql":
            # MySQL ignores conditional UniqueConstraint. NULL values do not collide
            # in a UNIQUE index, so only active rows receive guard=1.
            cursor.execute(
                f"ALTER TABLE {table} ADD COLUMN {schema_editor.quote_name(GUARD_COLUMN)} "
                "TINYINT GENERATED ALWAYS AS ("
                "CASE WHEN status IN ('OPEN', 'ACKNOWLEDGED', 'SNOOZED') "
                "THEN 1 ELSE NULL END) STORED"
            )
            cursor.execute(
                f"CREATE UNIQUE INDEX {index} ON {table} "
                f"(tenant_id, dedupe_key, {schema_editor.quote_name(GUARD_COLUMN)})"
            )
            return

        if vendor in {"postgresql", "sqlite"}:
            cursor.execute(f"DROP INDEX IF EXISTS {index}")
            cursor.execute(
                f"CREATE UNIQUE INDEX {index} ON {table} (tenant_id, dedupe_key) "
                "WHERE status IN ('OPEN', 'ACKNOWLEDGED', 'SNOOZED')"
            )
            return

        raise RuntimeError(
            f"Unsupported database vendor {vendor!r} for active-alert uniqueness backstop"
        )


def uninstall_active_alert_backstop(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    table = schema_editor.quote_name(_table_name(apps))
    index = schema_editor.quote_name(INDEX_NAME)

    with schema_editor.connection.cursor() as cursor:
        if vendor == "mysql":
            cursor.execute(f"DROP INDEX {index} ON {table}")
            cursor.execute(
                f"ALTER TABLE {table} DROP COLUMN {schema_editor.quote_name(GUARD_COLUMN)}"
            )
            return

        if vendor in {"postgresql", "sqlite"}:
            cursor.execute(f"DROP INDEX IF EXISTS {index}")
            cursor.execute(
                f"CREATE UNIQUE INDEX {index} ON {table} "
                "(tenant_id, dedupe_key, status) "
                "WHERE status IN ('OPEN', 'ACKNOWLEDGED', 'SNOOZED')"
            )
            return

        raise RuntimeError(
            f"Unsupported database vendor {vendor!r} for active-alert uniqueness backstop"
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("hr_control_center", "0002_hrcontrolcenterpermissionmeta"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    install_active_alert_backstop,
                    uninstall_active_alert_backstop,
                )
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="hralertinstance",
                    name=INDEX_NAME,
                ),
                migrations.AddConstraint(
                    model_name="hralertinstance",
                    constraint=models.UniqueConstraint(
                        fields=("tenant_id", "dedupe_key"),
                        condition=Q(status__in=ACTIVE_STATUSES),
                        name=INDEX_NAME,
                    ),
                ),
            ],
        ),
    ]
