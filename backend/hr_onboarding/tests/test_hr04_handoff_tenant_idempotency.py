from unittest.mock import call, patch

from django.test import SimpleTestCase

from hr_onboarding.integrations.hr04 import HandoffPayload, Hr04HandoffProvider


class Hr04HandoffTenantIdempotencyTests(SimpleTestCase):
    @patch("hr_onboarding.integrations.hr04.store_result")
    @patch("hr_onboarding.integrations.hr04.apply_idempotency", return_value=None)
    def test_same_raw_key_is_namespaced_by_tenant(self, apply_idempotency, store_result):
        provider = Hr04HandoffProvider()

        provider.consume_handoff(
            HandoffPayload(tenant_id=1, proposed_hire_id="hire-1", application_id="app-1"),
            "retry-key",
        )
        provider.consume_handoff(
            HandoffPayload(tenant_id=2, proposed_hire_id="hire-2", application_id="app-2"),
            "retry-key",
        )

        tenant_1_key = "hr05:handoff:tenant:1:retry-key"
        tenant_2_key = "hr05:handoff:tenant:2:retry-key"
        self.assertNotEqual(tenant_1_key, tenant_2_key)
        self.assertEqual(
            apply_idempotency.call_args_list,
            [call(tenant_1_key), call(tenant_2_key)],
        )
        self.assertEqual(store_result.call_args_list[0].args[0], tenant_1_key)
        self.assertEqual(store_result.call_args_list[1].args[0], tenant_2_key)
