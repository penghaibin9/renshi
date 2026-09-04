from django.test import SimpleTestCase

from hr_onboarding.integrations.hr04 import HandoffPayload, Hr04HandoffProvider


class Hr04HandoffTenantIdempotencyTests(SimpleTestCase):
    def test_mapper_preserves_explicit_tenant_boundary(self):
        provider = Hr04HandoffProvider()

        tenant_1, replay_1 = provider.consume_handoff(
            HandoffPayload(tenant_id=1, proposed_hire_id="hire-1", application_id="app-1"),
            "retry-key",
        )
        tenant_2, replay_2 = provider.consume_handoff(
            HandoffPayload(tenant_id=2, proposed_hire_id="hire-2", application_id="app-2"),
            "retry-key",
        )
        self.assertEqual(tenant_1["tenant_id"], 1)
        self.assertEqual(tenant_2["tenant_id"], 2)
        self.assertFalse(replay_1)
        self.assertFalse(replay_2)
