import uuid
from datetime import date

from django.test import TestCase
from django.utils import timezone

from hr_exit.models import ExitCase, ExitFact, RetirementFact, RetirementPrecheck
from hr_exit.services.retirement_service import RetirementFactError, RetirementFactService


class RetirementFactServiceTests(TestCase):
    def _exit_fact(self, *, status=ExitFact.Status.EFFECTIVE, exit_type=ExitCase.ExitType.RETIREMENT):
        fact = ExitFact(
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
        if status != ExitFact.Status.EFFECT_PENDING:
            fact.sealed_at = timezone.now()
            fact.content_hash = fact.calculate_content_hash()
        fact.save(force_insert=True)
        return fact

    def _precheck(self, exit_fact, *, decision=RetirementPrecheck.Decision.ELIGIBLE):
        return RetirementPrecheck.objects.create(
            tenant_id=77,
            idempotency_key=f"precheck-{uuid.uuid4()}",
            person_id=exit_fact.person_id,
            employment_relationship_id=exit_fact.employment_relationship_id,
            as_of=exit_fact.employment_end_date,
            decision=decision,
            retirement_type="STATUTORY",
            statutory_date=exit_fact.employment_end_date,
            matched_policy_id=uuid.uuid4(),
            matched_policy_version=1,
            input_snapshot_json={},
            explanation_json={},
        )

    def test_effective_retirement_exit_materializes_append_only_retirement_fact(self):
        exit_fact = self._exit_fact()
        precheck = self._precheck(exit_fact)
        result = RetirementFactService(77, actor_user_id=9).finalize(
            exit_fact_id=exit_fact.id,
            fact_no="RET-2026-001",
            precheck_id=precheck.id,
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
            precheck_id=precheck.id,
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
                precheck_id=uuid.uuid4(),
                retirement_type="STATUTORY",
            )
        self.assertEqual(ctx.exception.code, "RETIREMENT_FACT_NO_INVALID")

    def test_non_effective_or_non_retirement_exit_cannot_create_retirement_fact(self):
        pending = self._exit_fact(status=ExitFact.Status.EFFECT_PENDING)
        pending_precheck = self._precheck(pending)
        with self.assertRaises(RetirementFactError) as ctx:
            RetirementFactService(77).finalize(
                exit_fact_id=pending.id,
                fact_no="RET-PENDING",
                precheck_id=pending_precheck.id,
                retirement_type="STATUTORY",
            )
        self.assertEqual(ctx.exception.code, "RETIREMENT_EXIT_NOT_EFFECTIVE")

        resignation = self._exit_fact(exit_type=ExitCase.ExitType.RESIGNATION)
        resignation_precheck = self._precheck(resignation)
        with self.assertRaises(RetirementFactError) as ctx:
            RetirementFactService(77).finalize(
                exit_fact_id=resignation.id,
                fact_no="RET-WRONG-TYPE",
                precheck_id=resignation_precheck.id,
                retirement_type="STATUTORY",
            )
        self.assertEqual(ctx.exception.code, "RETIREMENT_EXIT_TYPE_REQUIRED")

    def test_one_effective_exit_cannot_silently_spawn_two_retirement_facts(self):
        exit_fact = self._exit_fact()
        precheck = self._precheck(exit_fact)
        service = RetirementFactService(77)
        service.finalize(
            exit_fact_id=exit_fact.id,
            fact_no="RET-ONE",
            precheck_id=precheck.id,
            retirement_type="STATUTORY",
        )

        with self.assertRaises(RetirementFactError) as ctx:
            service.finalize(
                exit_fact_id=exit_fact.id,
                fact_no="RET-TWO",
                precheck_id=precheck.id,
            )

        self.assertEqual(ctx.exception.code, "RETIREMENT_FACT_ALREADY_EXISTS")
        self.assertEqual(
            RetirementFact.objects.filter(tenant_id=77, exit_fact_id=exit_fact.id).count(),
            1,
        )

    def test_retirement_fact_is_tenant_scoped(self):
        exit_fact = self._exit_fact()
        precheck = self._precheck(exit_fact)
        with self.assertRaises(RetirementFactError) as ctx:
            RetirementFactService(88).finalize(
                exit_fact_id=exit_fact.id,
                fact_no="RET-XTENANT",
                precheck_id=precheck.id,
                retirement_type="STATUTORY",
            )
        self.assertEqual(ctx.exception.code, "EXIT_FACT_NOT_FOUND")

    def test_pension_processing_status_is_monotonic(self):
        exit_fact = self._exit_fact()
        precheck = self._precheck(exit_fact)
        fact = RetirementFactService(77).finalize(
            exit_fact_id=exit_fact.id,
            fact_no="RET-PENSION",
            precheck_id=precheck.id,
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
    def test_formal_retirement_rejects_missing_or_mismatched_precheck(self):
        exit_fact = self._exit_fact()
        with self.assertRaises(RetirementFactError) as ctx:
            RetirementFactService(77).finalize(
                exit_fact_id=exit_fact.id,
                fact_no="RET-NO-PRECHECK",
                precheck_id=uuid.uuid4(),
            )
        self.assertEqual(ctx.exception.code, "RETIREMENT_PRECHECK_REQUIRED")

        wrong = RetirementPrecheck.objects.create(
            tenant_id=77,
            idempotency_key=f"precheck-{uuid.uuid4()}",
            person_id=uuid.uuid4(),
            employment_relationship_id=exit_fact.employment_relationship_id,
            as_of=exit_fact.employment_end_date,
            decision=RetirementPrecheck.Decision.ELIGIBLE,
            retirement_type="STATUTORY",
            statutory_date=exit_fact.employment_end_date,
            input_snapshot_json={},
            explanation_json={},
        )
        with self.assertRaises(RetirementFactError) as ctx:
            RetirementFactService(77).finalize(
                exit_fact_id=exit_fact.id,
                fact_no="RET-WRONG-PRECHECK",
                precheck_id=wrong.id,
            )
        self.assertEqual(ctx.exception.code, "RETIREMENT_PRECHECK_SUBJECT_MISMATCH")
