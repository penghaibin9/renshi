from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from base.upload_security import MalwareScanError

from horilla.urls import readiness_check


@override_settings(MALWARE_SCAN_REQUIRED=False)
class ReadinessProbeTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/ready/")

    @patch("horilla.urls.cache")
    @patch("horilla.urls.connection")
    def test_readiness_executes_real_database_round_trip(self, connection, cache):
        connection.vendor = "mysql"
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        connection.cursor.return_value.__enter__.return_value = cursor
        cache.get.return_value = "1"

        response = readiness_check(self.request)

        self.assertEqual(response.status_code, 200)
        cursor.execute.assert_called_once_with("SELECT 1")

    @patch("horilla.urls.cache")
    @patch("horilla.urls.connection")
    def test_stale_database_connection_fails_readiness(self, connection, cache):
        connection.cursor.return_value.__enter__.side_effect = OSError("socket closed")

        response = readiness_check(self.request)

        self.assertEqual(response.status_code, 503)
        connection.close.assert_called_once_with()
        cache.set.assert_not_called()

    @override_settings(MALWARE_SCAN_REQUIRED=True)
    @patch("horilla.urls.ping_malware_scanner")
    @patch("horilla.urls.cache")
    @patch("horilla.urls.connection")
    def test_required_scanner_is_part_of_readiness(self, connection, cache, ping):
        connection.vendor = "mysql"
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        connection.cursor.return_value.__enter__.return_value = cursor
        cache.get.return_value = "1"

        response = readiness_check(self.request)

        self.assertEqual(response.status_code, 200)
        ping.assert_called_once_with()
        self.assertIn(b'"malware_scanner": "ok"', response.content)

    @override_settings(MALWARE_SCAN_REQUIRED=True)
    @patch("horilla.urls.ping_malware_scanner")
    @patch("horilla.urls.cache")
    @patch("horilla.urls.connection")
    def test_scanner_outage_fails_readiness(self, connection, cache, ping):
        connection.vendor = "mysql"
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        connection.cursor.return_value.__enter__.return_value = cursor
        cache.get.return_value = "1"
        ping.side_effect = MalwareScanError("scanner_unavailable", "offline")

        response = readiness_check(self.request)

        self.assertEqual(response.status_code, 503)
        self.assertIn(b'"malware_scanner": "unavailable"', response.content)
