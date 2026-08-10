"""MySQL schema compatibility for legacy Horilla migrations.

The upstream base.Company model stores ``address`` as ``TextField(max_length=255)``
while the historical ``base.0002_initial`` migration declares
``unique_together = (company, address)``. MySQL cannot create a normal unique
index over a TEXT column without a prefix length, so a fresh MySQL database
fails before any HR-domain migration can run.

Do not weaken the migration gate or fake the migration. Instead, keep Django's
migration state unchanged and translate only this one legacy constraint into a
MySQL prefix unique index. The application contract already caps address at
255 characters, therefore ``address(255)`` preserves the intended uniqueness
for valid application data.
"""

from __future__ import annotations

from django.db.backends.mysql.schema import DatabaseSchemaEditor


class HorillaMySQLSchemaEditor(DatabaseSchemaEditor):
    """Narrow compatibility shim for one legacy TEXT unique constraint."""

    _COMPANY_TABLE = "base_company"
    _COMPANY_UNIQUE = ("company", "address")
    _COMPANY_UNIQUE_INDEX = "uniq_base_company_company_address"
    _ADDRESS_PREFIX_LENGTH = 255

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
