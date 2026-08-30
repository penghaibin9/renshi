"""TransactionTestCase support for MySQL databases with immutable triggers.

Production evidence tables correctly reject DELETE, while Django implements
TransactionTestCase isolation with a database-wide flush.  Preserve and
temporarily remove test-database triggers only around that framework flush,
then restore the exact server definitions before the next test starts.
"""

from django.db import connection
from django.test import TransactionTestCase


class MySQLTriggerSafeTransactionTestCase(TransactionTestCase):
    def _fixture_teardown(self):
        trigger_definitions = []
        if connection.vendor == "mysql":
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS "
                    "WHERE TRIGGER_SCHEMA = DATABASE()"
                )
                trigger_names = [row[0] for row in cursor.fetchall()]
                for trigger_name in trigger_names:
                    quoted = trigger_name.replace("`", "``")
                    cursor.execute(f"SHOW CREATE TRIGGER `{quoted}`")
                    trigger_definitions.append(cursor.fetchone()[2])
                for trigger_name in trigger_names:
                    quoted = trigger_name.replace("`", "``")
                    cursor.execute(f"DROP TRIGGER IF EXISTS `{quoted}`")
        try:
            super()._fixture_teardown()
        finally:
            if trigger_definitions:
                with connection.cursor() as cursor:
                    for statement in trigger_definitions:
                        cursor.execute(statement)
