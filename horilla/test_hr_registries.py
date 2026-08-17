"""Contract tests for the HR01-HR18 canonical registries."""

import pytest

from horilla.hr_event_registry import BusinessEventDefinition, GlobalEventRegistry
from horilla.hr_permission_registry import (
    CanonicalPermissionRegistry,
    HR_DOMAINS,
    PermissionDefinition,
)
from horilla.hr_permissions import CANONICAL_PREFIX_ALIASES, permission_aliases


def test_permission_domain_map_covers_hr01_hr18_exactly():
    assert tuple(HR_DOMAINS) == tuple("HR%02d" % i for i in range(1, 19))
    assert len(set(HR_DOMAINS.values())) == 18
    assert tuple(CANONICAL_PREFIX_ALIASES) == tuple("hr%02d." % i for i in range(1, 19))
    for module_code, domain in HR_DOMAINS.items():
        legacy = module_code.lower() + ".agreement.view"
        canonical = "hr.%s.agreement.view" % domain
        assert canonical in permission_aliases(legacy)


def test_permission_registry_rejects_wrong_domain_and_conflicting_duplicate():
    registry = CanonicalPermissionRegistry()
    definition = PermissionDefinition("hr.contracts.agreement.read", "HR07", "read")
    registry.register(definition)
    registry.register(definition)
    assert registry.get(definition.key) == definition

    with pytest.raises(ValueError):
        registry.register(
            PermissionDefinition("hr.staff.agreement.read", "HR07", "wrong domain")
        )
    with pytest.raises(ValueError):
        registry.register(
            PermissionDefinition("hr.contracts.agreement.read", "HR07", "changed")
        )


def test_event_registry_is_versioned_and_domain_bound():
    registry = GlobalEventRegistry()
    v1 = BusinessEventDefinition(
        "hr.contracts.agreement.effective", "HR07", "agreement", 1
    )
    v2 = BusinessEventDefinition(
        "hr.contracts.agreement.effective", "HR07", "agreement", 2
    )
    registry.register(v1, v2)
    assert registry.get(v1.name, 1) == v1
    assert registry.get(v2.name, 2) == v2

    with pytest.raises(ValueError):
        registry.register(
            BusinessEventDefinition(
                "hr.staff.agreement.effective", "HR07", "agreement", 1
            )
        )
    with pytest.raises(ValueError):
        registry.register(
            BusinessEventDefinition(
                "hr.contracts.contract.effective", "HR07", "agreement", 1
            )
        )
