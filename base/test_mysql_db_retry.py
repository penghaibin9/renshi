from types import SimpleNamespace
from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase

from horilla.db_retry import mysql_operational_error_code, retry_mysql_transaction


class MysqlTransactionRetryTests(SimpleTestCase):
    def test_extracts_mysql_code_from_wrapped_cause(self):
        root = OperationalError(1213, "deadlock")
        wrapper = RuntimeError("outer")
        wrapper.__cause__ = root
        self.assertEqual(mysql_operational_error_code(wrapper), 1213)

    @patch("horilla.db_retry.time.sleep")
    @patch("horilla.db_retry.connection", new=SimpleNamespace(vendor="mysql"))
    def test_deadlock_retries_whole_boundary_then_succeeds(self, sleep):
        calls = []

        @retry_mysql_transaction(attempts=3, base_delay_seconds=0.01)
        def boundary():
            calls.append(len(calls) + 1)
            if len(calls) < 3:
                raise OperationalError(1213, "deadlock found")
            return "ok"

        self.assertEqual(boundary(), "ok")
        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual([item.args[0] for item in sleep.call_args_list], [0.01, 0.02])

    @patch("horilla.db_retry.time.sleep")
    @patch("horilla.db_retry.connection", new=SimpleNamespace(vendor="mysql"))
    def test_lock_wait_timeout_is_retryable(self, sleep):
        calls = 0

        @retry_mysql_transaction(attempts=2, base_delay_seconds=0)
        def boundary():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OperationalError(1205, "lock wait timeout")
            return 7

        self.assertEqual(boundary(), 7)
        self.assertEqual(calls, 2)
        sleep.assert_not_called()

    @patch("horilla.db_retry.connection", new=SimpleNamespace(vendor="mysql"))
    def test_non_transient_mysql_error_is_not_retried(self):
        calls = 0

        @retry_mysql_transaction(attempts=3, base_delay_seconds=0)
        def boundary():
            nonlocal calls
            calls += 1
            raise OperationalError(1062, "duplicate key")

        with self.assertRaises(OperationalError):
            boundary()
        self.assertEqual(calls, 1)

    @patch("horilla.db_retry.connection", new=SimpleNamespace(vendor="sqlite"))
    def test_non_mysql_database_error_is_not_retried(self):
        calls = 0

        @retry_mysql_transaction(attempts=3, base_delay_seconds=0)
        def boundary():
            nonlocal calls
            calls += 1
            raise OperationalError(1213, "deadlock-shaped but not mysql")

        with self.assertRaises(OperationalError):
            boundary()
        self.assertEqual(calls, 1)

    @patch("horilla.db_retry.connection", new=SimpleNamespace(vendor="mysql"))
    def test_exhausted_attempts_reraises_last_operational_error(self):
        calls = 0

        @retry_mysql_transaction(attempts=2, base_delay_seconds=0)
        def boundary():
            nonlocal calls
            calls += 1
            raise OperationalError(1213, "still deadlocked")

        with self.assertRaises(OperationalError) as ctx:
            boundary()
        self.assertEqual(ctx.exception.args[0], 1213)
        self.assertEqual(calls, 2)
