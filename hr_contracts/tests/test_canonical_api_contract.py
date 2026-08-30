"""HR07 canonical API registration and governance contracts."""

from django.test import SimpleTestCase
from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry

from hr_contracts.api_urls import urlpatterns
from hr_contracts.events import (
    EVENT_AGREEMENT_CREATED,
    EVENT_AGREEMENT_EFFECTIVE,
    EVENT_AGREEMENT_SIGNED,
    EVENT_AGREEMENT_TERMINATED,
)
from hr_contracts.permissions import (
    PERM_AGREEMENT_ACTIVATE,
    PERM_AGREEMENT_CREATE,
    PERM_AGREEMENT_SIGN,
    PERM_AGREEMENT_VIEW,
    PERM_CASE_ACTIVATE,
    PERM_CASE_APPROVE,
    PERM_CASE_CREATE,
    PERM_CASE_SIGN,
    PERM_CASE_SUBMIT,
    PERM_CASE_TERMINATE,
)


def test_hr07_canonical_routes_are_registered_without_recovery_only_modules():
    routes = {str(pattern.pattern) for pattern in urlpatterns}
    expected = {
        "api/v1/hr/contracts/agreements",
        "api/v1/hr/contracts/agreements/<uuid:agreement_id>/versions/sign",
        (
            "api/v1/hr/contracts/agreements/<uuid:agreement_id>/versions/"
            "<uuid:version_id>/activate"
        ),
        "api/v1/hr/contracts/cases",
        "api/v1/hr/contracts/cases/<uuid:case_id>",
        "api/v1/hr/contracts/cases/<uuid:case_id>/submit",
        "api/v1/hr/contracts/cases/<uuid:case_id>/approve",
        "api/v1/hr/contracts/cases/<uuid:case_id>/versions/sign",
        (
            "api/v1/hr/contracts/cases/<uuid:case_id>/versions/"
            "<uuid:version_id>/activate"
        ),
        "api/v1/hr/contracts/cases/<uuid:case_id>/termination/effect",
    }
    assert expected <= routes


def test_hr07_permissions_use_global_registry():
    for key in (
        PERM_AGREEMENT_VIEW,
        PERM_AGREEMENT_CREATE,
        PERM_AGREEMENT_SIGN,
        PERM_AGREEMENT_ACTIVATE,
        PERM_CASE_CREATE,
        PERM_CASE_SUBMIT,
        PERM_CASE_APPROVE,
        PERM_CASE_SIGN,
        PERM_CASE_ACTIVATE,
        PERM_CASE_TERMINATE,
    ):
        definition = permission_registry.get(key)
        assert definition.module_code == "HR07"
        assert definition.key.split(".")[1] == "contracts"


def test_hr07_events_use_global_registry():
    for event_name in (
        EVENT_AGREEMENT_CREATED,
        EVENT_AGREEMENT_SIGNED,
        EVENT_AGREEMENT_EFFECTIVE,
        EVENT_AGREEMENT_TERMINATED,
    ):
        definition = global_event_registry.get(event_name, 1)
        assert definition.module_code == "HR07"
        assert definition.aggregate == "agreement"
        assert definition.name.split(".")[1] == "contracts"


class Hr07RegistryContractTests(SimpleTestCase):
    def test_module_code_and_domain_are_canonical(self):
        for key in (
            PERM_AGREEMENT_VIEW,
            PERM_AGREEMENT_CREATE,
            PERM_AGREEMENT_SIGN,
            PERM_AGREEMENT_ACTIVATE,
            PERM_CASE_CREATE,
            PERM_CASE_SUBMIT,
            PERM_CASE_APPROVE,
            PERM_CASE_SIGN,
            PERM_CASE_ACTIVATE,
            PERM_CASE_TERMINATE,
        ):
            definition = permission_registry.get(key)
            self.assertEqual(definition.module_code, "HR07")
            self.assertEqual(definition.key.split(".")[1], "contracts")

        for event_name in (
            EVENT_AGREEMENT_CREATED,
            EVENT_AGREEMENT_SIGNED,
            EVENT_AGREEMENT_EFFECTIVE,
            EVENT_AGREEMENT_TERMINATED,
        ):
            definition = global_event_registry.get(event_name, 1)
            self.assertEqual(definition.module_code, "HR07")
            self.assertEqual(definition.name.split(".")[1], "contracts")
