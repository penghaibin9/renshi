import uuid
from datetime import date

from django.test import TestCase

from hr_exit.models import ExitCase, ExitFact, RetirementFact
from hr_exit.services.retirement_service import RetirementFactError, RetirementFactService


class RetirementFactServiceTests(TestCase):
    def _exit_fact(self, *, status=ExitFact.Status.EFFECTIVE, exit_type=ExitCase.ExitType.RETIREMENT):
        return ExitFact.objects.create(
            tenant_id=77,
            fact_no=f"EXIT-{uuid.uuid4().hex[:8]}",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            source_case_id=uuid.uuid4(),
            exit_type=exit_type,
            employment_end_date=date(2026, 9, 1),
            last_working_date=date(2026, 8, 31),
            status=status,
        )

    def test_effective_retirement_exit_materializes_append_only_retirement_fact(self):
        exit_fact = self._exit_fact()
        result = RetirementFactService(77, actor_user_id=9).finalize(
            exit_fact_id=exit_fact.id,
            fact_no="RET-2026-001",
            retirement_type="STATUTORY",
            statutory_date=date(2026, 9, 1),
        )

        self.assertTrue(result.created)
        self.assertEqual(result.fact.person_id, exit_fact.person_id)
        self.assertEqual(result.fact.exit_fact_id, exit_fact.id)
        self.assertEqual(result.fact.effective_date, exit_fact.employment_end_date)
        self.assertEqual(
            result.fact.pension_processing_status,
            RetirementFact.PensionStatus.NOT_STARTED,
        )
        self.assertEqual(result.fact.status, ExitFact.Status.EFFECTIVE)

        replay = RetirementFactService(77).finalize(
            exit_fact_id=exit_fact.id,
            fact_no="RET-2026-001",
            retirement_type="STATUTORY",
            statutory_date=date(2026, 9, 1),
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.fact.id, result.fact.id)

    def test_retirement_fact_no_length_fails_before_database_work(self):
        with self.assertRaises(RetirementFactError) as ctx:
            RetirementFactService(77).finalize(
                exit_fact_id=uuid.uuid4(),
                fact_no="X" * 65,
                retirement_type="STATUTORY",
            )
        self.assertEqual(ctx.exception.code, "RETIREMENT_FACT_NO_INVALID")

    def test_non_effective_or_non_retirement_exit_cannot_create_retirement_fact(self):
        pending = self._exit_fact(status=ExitFact.Status.EFFECT_PENDING)
        with self.assertRaises(RetirementFactError) as ctx:
            RetirementFactService(77).finalize(
                exit_fact_id=pending.id,
                fact_no="RET-PENDING",
                retirement_type="STATUTORY",
            )
        self.assertEqual(ctx.exception.code, "RETIREMENT_EXIT_NOT_EFFECTIVE")

        resignation = self._exit_fact(exit_type=ExitCase.ExitType.RESIGNATION)
        with self.assertRaises(RetirementFactError) as ctx:
            RetirementFactService(77).finalize(
                exit_fact_id=resignation.id,
                fact_no="RET-WRONG-TYPE",
                retirement_type="STATUTORY",
            )
        self.assertEqual(ctx.exception.code, "RETIREMENT_EXIT_TYPE_REQUIRED")

    def test_one_effective_exit_cannot_silently_spawn_two_retirement_facts(self):
        exit_fact = self._exit_fact()
        service = RetirementFactService(77)
        service.finalize(
            exit_fact_id=exit_fact.id,
            fact_no="RET-ONE",
            retirement_type="STATUTORY",
        )

        with self.assertRaises(RetirementFactError) as ctx:
            service.finalize(
                exit_fact_id=exit_fact.id,
                fact_no="RET-TWO",
                retirement_type="EARLY",
            )

        self.assertEqual(ctx.exception.code, "RETIREMENT_FACT_ALREADY_EXISTS")
        self.assertEqual(
            RetirementFact.objects.filter(tenant_id=77, exit_fact_id=exit_fact.id).count(),
            1,
        )

    def test_retirement_fact_is_tenant_scoped(self):
        exit_fact = self._exit_fact()
        with self.assertRaises(RetirementFactError) as ctx:
            RetirementFactService(88).finalize(
                exit_fact_id=exit_fact.id,
                fact_no="RET-XTENANT",
                retirement_type="STATUTORY",
            )
        self.assertEqual(ctx.exception.code, "EXIT_FACT_NOT_FOUND")

    def test_pension_processing_status_is_monotonic(self):
        exit_fact = self._exit_fact()
        fact = RetirementFactService(77).finalize(
            exit_fact_id=exit_fact.id,
            fact_no="RET-PENSION",
            retirement_type="STATUTORY",
        ).fact
        service = RetirementFactService(77, actor_user_id=9)

        service.set_pension_status(
            fact.id, status=RetirementFact.PensionStatus.IN_PROGRESS
        )
        completed = service.set_pension_status(
            fact.id, status=RetirementFact.PensionStatus.COMPLETED
        )
        self.assertEqual(
            completed.pension_processing_status,
            RetirementFact.PensionStatus.COMPLETED,
        )

        with self.assertRaises(RetirementFactError) as ctx:
            service.set_pension_status(
                fact.id, status=RetirementFact.PensionStatus.IN_PROGRESS
            )
        self.assertEqual(ctx.exception.code, "RETIREMENT_PENSION_STATUS_REGRESSION")
