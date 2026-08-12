"""MySQL-compatible physical enforcement for Allowance semantic uniqueness.

``payroll.0001`` carries the historical Django state for a 16-column
``unique_together``. Under utf8mb4 its worst-case key is wider than InnoDB's
3072-byte limit. ``HorillaMySQLSchemaEditor`` therefore suppresses only that
impossible physical index on MySQL; this migration installs an equivalent
compact UNIQUE key over a virtual SHA-256 generated column.

Important semantics:
- the generated expression becomes NULL when *any* original key member is NULL,
  matching MySQL composite-UNIQUE NULL behavior;
- every non-NULL member is length-prefixed before hashing, avoiding ambiguous
  concatenation boundaries;
- existing databases that already have a real unique constraint across the
  original columns are left untouched;
- duplicate existing rows make this migration fail rather than silently weaken
  the invariant.
"""

from django.db import migrations


TARGET_FIELDS = (
    "title",
    "is_taxable",
    "is_condition_based",
    "field",
    "condition",
    "value",
    "is_fixed",
    "amount",
    "based_on",
    "rate",
    "per_attendance_fixed_amount",
    "shift_id",
    "shift_per_attendance_amount",
    "amount_per_one_hr",
    "work_type_id",
    "work_type_per_attendance_amount",
)

HASH_COLUMN = "_semantic_unique_hash"
HASH_INDEX = "uniq_payroll_allowance_semantic_hash"


def _target_columns(allowance):
    return [allowance._meta.get_field(name).column for name in TARGET_FIELDS]


def _has_original_unique(schema_editor, table, columns):
    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(cursor, table)
    target = list(columns)
    return any(
        details.get("unique") and list(details.get("columns") or []) == target
        for details in constraints.values()
    )


def _column_exists(schema_editor, table, column):
    with schema_editor.connection.cursor() as cursor:
        description = schema_editor.connection.introspection.get_table_description(
            cursor, table
        )
    return any(item.name == column for item in description)


def _index_exists(schema_editor, table, index_name):
    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(cursor, table)
    return index_name in constraints


def _hash_expression(schema_editor, columns):
    quote = schema_editor.quote_name
    parts = []
    for column in columns:
        qcol = quote(column)
        value = f"CAST({qcol} AS CHAR)"
        # CONCAT returns NULL as soon as any argument is NULL. Consequently the
        # hash is NULL whenever one of the original composite-key values is
        # NULL, exactly like a normal MySQL composite UNIQUE key.
        parts.extend(
            [
                f"LPAD(OCTET_LENGTH({value}), 10, '0')",
                "':'",
                value,
            ]
        )
    return "UNHEX(SHA2(CONCAT(" + ", ".join(parts) + "), 256))"


def install_mysql_allowance_unique(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    allowance = apps.get_model("payroll", "Allowance")
    table_name = allowance._meta.db_table
    columns = _target_columns(allowance)

    # Some older installations may have been created under a charset/key setup
    # where the historical physical composite key succeeded. Do not duplicate it.
    if _has_original_unique(schema_editor, table_name, columns):
        return

    table = schema_editor.quote_name(table_name)
    hash_column = schema_editor.quote_name(HASH_COLUMN)
    hash_index = schema_editor.quote_name(HASH_INDEX)

    if not _column_exists(schema_editor, table_name, HASH_COLUMN):
        expression = _hash_expression(schema_editor, columns)
        schema_editor.execute(
            f"ALTER TABLE {table} ADD COLUMN {hash_column} BINARY(32) "
            f"GENERATED ALWAYS AS ({expression}) VIRTUAL"
        )

    if not _index_exists(schema_editor, table_name, HASH_INDEX):
        schema_editor.execute(
            f"CREATE UNIQUE INDEX {hash_index} ON {table} ({hash_column})"
        )


def remove_mysql_allowance_unique(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    allowance = apps.get_model("payroll", "Allowance")
    table_name = allowance._meta.db_table
    table = schema_editor.quote_name(table_name)

    if _index_exists(schema_editor, table_name, HASH_INDEX):
        schema_editor.execute(
            f"DROP INDEX {schema_editor.quote_name(HASH_INDEX)} ON {table}"
        )
    if _column_exists(schema_editor, table_name, HASH_COLUMN):
        schema_editor.execute(
            f"ALTER TABLE {table} DROP COLUMN {schema_editor.quote_name(HASH_COLUMN)}"
        )


class Migration(migrations.Migration):
    # MySQL cannot execute ALTER TABLE / CREATE INDEX safely inside Django's
    # migration transaction because DDL is not rollback-capable. Keep the
    # semantic invariant strict, but run this compatibility DDL non-atomically.
    atomic = False

    dependencies = [("payroll", "0004_alter_allowance_include_active_employees_and_more")]

    operations = [
        migrations.RunPython(
            install_mysql_allowance_unique,
            remove_mysql_allowance_unique,
        )
    ]
