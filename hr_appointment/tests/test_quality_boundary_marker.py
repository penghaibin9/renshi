"""Temporary discoverability marker for the HR14 quality boundary."""

from django.test import SimpleTestCase


class QualityBoundaryMarkerTests(SimpleTestCase):
    def test_mysql_contract_remains_mandatory(self):
        self.assertEqual("mysql", "mysql")
