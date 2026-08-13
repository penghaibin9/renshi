from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_self.services.identity_service import SelfIdentityContext
from hr_self.services.provider_gateway import (
    ProviderStatus,
    SelfProviderRegistry,
    SelfProviderResult,
    hr03_self_provider,
)


class Hr17ProviderGatewayTests(SimpleTestCase):
    def setUp(self):
        self.context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id="00000000-0000-0000-0000-000000000301",
            person_id="00000000-0000-0000-0000-000000000201",
            legacy_employee_id=51,
        )

    def test_unregistered_source_is_unavailable_not_empty_business_data(self):
        registry = SelfProviderRegistry()
        result = registry.call("HR07", self.context)
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertIsNone(result.data)
        self.assertEqual(result.error_code, "SOURCE_PROVIDER_NOT_REGISTERED")

    def test_one_provider_error_does_not_take_down_other_sources(self):
        registry = SelfProviderRegistry()
        registry.register("HR03", lambda context: SelfProviderResult.ok({"staff": "ok"}))

        def broken(_context):
            raise RuntimeError("source database unavailable")

        registry.register("HR09", broken)
        results = registry.collect(self.context)
        self.assertEqual(results["HR03"].status, ProviderStatus.OK)
        self.assertEqual(results["HR03"].data, {"staff": "ok"})
        self.assertEqual(results["HR09"].status, ProviderStatus.ERROR)
        self.assertIsNone(results["HR09"].data)
        self.assertEqual(results["HR09"].error_code, "SOURCE_PROVIDER_ERROR")
        self.assertEqual(results["HR10"].status, ProviderStatus.UNAVAILABLE)

    def test_partial_status_is_preserved_and_not_promoted_to_ok(self):
        registry = SelfProviderRegistry()
        registry.register(
            "HR10",
            lambda context: SelfProviderResult(
                status=ProviderStatus.PARTIAL,
                data={"items": []},
                error_code="SOURCE_PARTIAL",
                error_message="one upstream is incomplete",
            ),
        )
        result = registry.call("HR10", self.context)
        self.assertEqual(result.status, ProviderStatus.PARTIAL)
        self.assertEqual(result.data, {"items": []})

    def test_invalid_provider_envelope_becomes_source_error(self):
        registry = SelfProviderRegistry()
        registry.register("HR11", lambda context: {"status": "OK"})
        result = registry.call("HR11", self.context)
        self.assertEqual(result.status, ProviderStatus.ERROR)
        self.assertEqual(result.error_code, "SOURCE_PROVIDER_CONTRACT_INVALID")
        self.assertIsNone(result.data)

    @patch("hr_staff.selectors.profile.ProfileSelector")
    @patch("hr_staff.context.build_staff_context")
    def test_hr03_provider_builds_server_side_self_scope(self, build_context, selector_cls):
        hr03_context = SimpleNamespace(request_snapshot_at=None)
        build_context.return_value = hr03_context
        selector_cls.return_value.bootstrap.return_value = {
            "identityHeader": {"staffNo": "T001", "dataBasis": "HR03_AUTHORITY"},
            "currentFacts": {"primaryAssignment": {"positionName": "TEACHER"}},
        }

        result = hr03_self_provider(self.context)

        self.assertEqual(result.status, ProviderStatus.OK)
        build_context.assert_called_once_with(
            tenant_id=77,
            user_id=9,
            scope_type="SELF",
            scope_staff_ids=[self.context.staff_id],
            authority_mode="HR03_AUTHORITY",
        )
        selector_cls.assert_called_once_with(hr03_context)
        selector_cls.return_value.bootstrap.assert_called_once_with(self.context.staff_id)
        self.assertEqual(result.meta["scope"], "SELF")
        self.assertEqual(result.meta["authority"], "HR03_AUTHORITY")
