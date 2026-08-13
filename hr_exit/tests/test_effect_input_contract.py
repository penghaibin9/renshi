from django.test import SimpleTestCase

from hr_exit.services.effect_service import ExitEffectError, ExitEffectService


class ExitEffectInputContractTests(SimpleTestCase):
    def test_fact_no_is_required_before_saga_or_provider_work(self):
        service = ExitEffectService(77, actor_user_id=9)

        with self.assertRaises(ExitEffectError) as ctx:
            service.apply(
                case_id="00000000-0000-0000-0000-000000000001",
                fact_no="   ",
                idempotency_key="idem-1",
            )

        self.assertEqual(ctx.exception.code, "EXIT_FACT_NO_REQUIRED")

    def test_fact_no_cannot_exceed_storage_contract(self):
        service = ExitEffectService(77)

        with self.assertRaises(ExitEffectError) as ctx:
            service.apply(
                case_id="00000000-0000-0000-0000-000000000001",
                fact_no="X" * 65,
                idempotency_key="idem-2",
            )

        self.assertEqual(ctx.exception.code, "EXIT_FACT_NO_INVALID")
