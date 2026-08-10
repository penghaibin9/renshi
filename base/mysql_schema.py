"""MySQL schema compatibility for legacy Horilla migrations.

Keep historical Django migration *state* intact while translating a very small
set of legacy constraints that MySQL 8.4 cannot represent directly:

* ``base.Company(company, address)`` where ``address`` is TEXT; and
* the 16-column ``payroll.Allowance`` semantic unique key whose utf8mb4 key
  width exceeds InnoDB's 3072-byte limit.

The payroll logical uniqueness is installed by ``payroll.0005`` as a UNIQUE
index over a virtual SHA-256 generated column. The generated expression returns
NULL whenever any original key member is NULL, preserving MySQL composite
UNIQUE NULL semantics. This editor only suppresses the impossible physical
index from ``payroll.0001``; Django's migration state is not weakened.
"""

from __future__ import annotations

from django.db.backends.mysql.schema import DatabaseSchemaEditor


class HorillaMySQLSchemaEditor(DatabaseSchemaEditor):
    """Narrow compatibility shim for known legacy MySQL DDL incompatibilities."""

    _COMPANY_TABLE = "base_company"
    _COMPANY_UNIQUE = ("company", "address")
    _COMPANY_UNIQUE_INDEX = "uniq_base_company_company_address"
    _ADDRESS_PREFIX_LENGTH = 255

    _ALLOWANCE_TABLE = "payroll_allowance"
    _ALLOWANCE_OVERSIZED_UNIQUE = (
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

    def _create_unique_sql(self, model, fields, *args, **kwargs):
        """Skip only the impossible payroll physical key; 0005 installs its equivalent."""
        field_names = tuple(getattr(field, "name", None) for field in fields)
        if (
            model._meta.db_table == self._ALLOWANCE_TABLE
            and field_names == self._ALLOWANCE_OVERSIZED_UNIQUE
        ):
            return None
        return super()._create_unique_sql(model, fields, *args, **kwargs)

    def alter_unique_together(self, model, old_unique_together, new_unique_together):
        old_set = {tuple(fields) for fields in old_unique_together}
        new_set = {tuple(fields) for fields in new_unique_together}
        target = self._COMPANY_UNIQUE

        if model._meta.db_table != self._COMPANY_TABLE or (
            target not in old_set and target not in new_set
        ):
            return super().alter_unique_together(
                model, old_unique_together, new_unique_together
            )

        # Preserve normal Django behavior for any unrelated constraints that
        # might be altered in the same operation.
        passthrough_old = old_set - {target}
        passthrough_new = new_set - {target}
        if passthrough_old != passthrough_new:
            super().alter_unique_together(
                model,
                sorted(passthrough_old),
                sorted(passthrough_new),
            )

        table = self.quote_name(model._meta.db_table)
        company = self.quote_name(model._meta.get_field("company").column)
        address = self.quote_name(model._meta.get_field("address").column)
        index = self.quote_name(self._COMPANY_UNIQUE_INDEX)

        if target in new_set - old_set:
            self.execute(
                f"CREATE UNIQUE INDEX {index} ON {table} "
                f"({company}, {address}({self._ADDRESS_PREFIX_LENGTH}))"
            )
        elif target in old_set - new_set:
            self.execute(f"DROP INDEX {index} ON {table}")
