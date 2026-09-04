from unittest.mock import patch

from django.test import SimpleTestCase

from horilla_audit import registry


class AuditRegistryStartupTests(SimpleTestCase):
    @patch("horilla_audit.registry._load_targets")
    @patch("horilla_audit.registry._apply_targets")
    def test_default_startup_registration_does_not_load_database_targets(
        self, apply_targets, load_targets
    ):
        registry.apply_default_configuration()
        load_targets.assert_not_called()
        apply_targets.assert_called_once()
