"""Contract tests for the HR01-HR18 canonical registries.

These tests intentionally use unittest so Django's documented test command
collects them.  The former module-level pytest functions were imported but
silently counted as zero tests by Django's unittest runner.
"""

from django.test import SimpleTestCase

from horilla.hr_event_registry import BusinessEventDefinition, GlobalEventRegistry
from horilla.hr_permission_registry import (
    CanonicalPermissionRegistry,
    HR_DOMAINS,
    PermissionDefinition,
)
from horilla.hr_permissions import CANONICAL_PREFIX_ALIASES, permission_aliases


class CanonicalRegistryContractTests(SimpleTestCase):
    def test_permission_domain_map_covers_hr01_hr18_exactly(self):
        self.assertEqual(
            tuple(HR_DOMAINS), tuple("HR%02d" % i for i in range(1, 19))
        )
        self.assertEqual(len(set(HR_DOMAINS.values())), 18)
        self.assertEqual(
            tuple(CANONICAL_PREFIX_ALIASES),
            tuple("hr%02d." % i for i in range(1, 19)),
        )
        for module_code, domain in HR_DOMAINS.items():
            legacy = module_code.lower() + ".agreement.view"
            canonical = "hr.%s.agreement.view" % domain
            self.assertIn(canonical, permission_aliases(legacy))

    def test_permission_registry_rejects_wrong_domain_and_conflicting_duplicate(self):
        registry = CanonicalPermissionRegistry()
        definition = PermissionDefinition(
            "hr.contracts.agreement.read", "HR07", "read"
        )
        registry.register(definition)
        registry.register(definition)
        self.assertEqual(registry.get(definition.key), definition)

        with self.assertRaises(ValueError):
            registry.register(
                PermissionDefinition(
                    "hr.staff.agreement.read", "HR07", "wrong domain"
                )
            )
        with self.assertRaises(ValueError):
            registry.register(
                PermissionDefinition(
                    "hr.contracts.agreement.read", "HR07", "changed"
                )
            )

    def test_event_registry_is_versioned_and_domain_bound(self):
        registry = GlobalEventRegistry()
        v1 = BusinessEventDefinition(
            "hr.contracts.agreement.effective", "HR07", "agreement", 1
        )
        v2 = BusinessEventDefinition(
            "hr.contracts.agreement.effective", "HR07", "agreement", 2
        )
        registry.register(v1, v2)
        self.assertEqual(registry.get(v1.name, 1), v1)
        self.assertEqual(registry.get(v2.name, 2), v2)

        with self.assertRaises(ValueError):
            registry.register(
                BusinessEventDefinition(
                    "hr.staff.agreement.effective", "HR07", "agreement", 1
                )
            )
        with self.assertRaises(ValueError):
            registry.register(
                BusinessEventDefinition(
                    "hr.contracts.contract.effective", "HR07", "agreement", 1
                )
            )
