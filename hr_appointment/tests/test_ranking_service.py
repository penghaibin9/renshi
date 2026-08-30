import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from hr_assessment.models import (
    HrAssessmentCase,
    HrAssessmentCycle,
    HrCycleSnapshot,
    HrFinalAssessmentResult,
)
from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentBatch,
    AppointmentRankingResult,
)
from hr_appointment.population_models import (
    AppointmentPopulationMemberSnapshot,
    AppointmentPopulationSnapshot,
)
from hr_appointment.services.ranking_service import (
    AppointmentRankingError,
    AppointmentRankingService,
)
from hr_staff.models import HrOutboxEvent


class Hr14RankingServiceTests(TestCase):
    tenant_id = 7

    def setUp(self):
        now = timezone.now()
        self.batch = AppointmentBatch.objects.create(
            tenant_id=self.tenant_id,
            batch_no=f"BATCH-{uuid.uuid4().hex[:8]}",
            name="2026 岗位竞聘",
            policy_version_id=uuid.uuid4(),
            business_type="COMPETITIVE_APPOINTMENT",
            status=AppointmentBatch.Status.REVIEWING,
        )
        self.population = AppointmentPopulationSnapshot.objects.create(
            tenant_id=self.tenant_id,
            batch=self.batch,
            as_of_date=now.date(),
            snapshot_at=now,
            member_count=0,
            content_hash="p" * 64,
        )
        self.cycle = HrAssessmentCycle.objects.create(
            tenant_id=self.tenant_id,
            cycle_no=self.batch.batch_no,
            assessment_type=self.batch.business_type,
            name="竞聘评价",
            start_at=now - timedelta(days=10),
            end_at=now,
            policy_version_id=uuid.uuid4(),
            lifecycle_status="REVIEWING",
        )
        self.cycle_snapshot = HrCycleSnapshot.objects.create(
            tenant_id=self.tenant_id,
            cycle=self.cycle,
            frozen_reviewer_rules_json={
                "ranking": {"selectedCount": 1, "waitlistCount": 1}
            },
        )

    def _participant(self, score, *, person_id=None, with_result=True):
        person_id = person_id or uuid.uuid4()
        staff_id = uuid.uuid4()
        case = AppointmentApplicationCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=f"CASE-{uuid.uuid4().hex[:10]}",
            person_id=person_id,
            policy_version_id=self.batch.policy_version_id,
            position_instance_id=101,
            batch_no=self.batch.batch_no,
            requested_level_code="L2",
            status=AppointmentApplicationCase.Status.UNDER_REVIEW,
        )
        AppointmentPopulationMemberSnapshot.objects.create(
            tenant_id=self.tenant_id,
            snapshot=self.population,
            person_id=person_id,
            staff_id=staff_id,
            member_hash=uuid.uuid4().hex,
        )
        assessment_case = HrAssessmentCase.objects.create(
            tenant_id=self.tenant_id,
            assessment_type=self.batch.business_type,
            cycle=self.cycle,
            staff_id=staff_id,
            policy_version_id=self.cycle.policy_version_id,
            status="FINALIZED",
        )
        result = None
        if with_result:
            result = HrFinalAssessmentResult.objects.create(
                tenant_id=self.tenant_id,
                case_id=assessment_case.id,
                assessment_type=self.batch.business_type,
                cycle_id=self.cycle.id,
                grade_code="QUALIFIED",
                display_grade_snapshot_json={"zh-CN": "合格"},
                calculated_score=Decimal(str(score)).quantize(Decimal("0.01")),
                decision_reason="服务端评价",
                policy_version_id=self.cycle.policy_version_id,
                result_version_no=1,
                status="FINALIZED",
            )
        return case, assessment_case, result

    def test_score_rank_outcome_and_snapshot_are_derived_from_sealed_results(self):
        target, _, result = self._participant("91.25")
        self._participant("88.00")

        outcome = AppointmentRankingService(self.tenant_id, actor_user_id=88).finalize(
            case_id=target.id,
            ranking_no="RK-AUTH-1",
        )

        self.assertTrue(outcome.created)
        self.assertEqual(outcome.ranking.total_score, Decimal("91.2500"))
        self.assertEqual(outcome.ranking.rank_no, 1)
        self.assertEqual(outcome.ranking.outcome, AppointmentRankingResult.Outcome.SELECTED)
        self.assertEqual(
            outcome.ranking.score_snapshot_json["sourceAssessment"]["assessmentResultId"],
            str(result.id),
        )
        self.assertEqual(outcome.case.status, AppointmentApplicationCase.Status.PROPOSED)
        self.assertEqual(
            HrOutboxEvent.objects.filter(
                tenant_id=self.tenant_id,
                event_type="hr.appointment.ranking.published",
            ).count(),
            1,
        )

    def test_equal_scores_use_deterministic_person_then_case_tie_break(self):
        lower_person = uuid.UUID("00000000-0000-0000-0000-000000000001")
        higher_person = uuid.UUID("00000000-0000-0000-0000-000000000002")
        first, _, _ = self._participant("90", person_id=lower_person)
        second, _, _ = self._participant("90", person_id=higher_person)

        first_result = AppointmentRankingService(self.tenant_id).finalize(
            case_id=first.id, ranking_no="RK-TIE-1"
        ).ranking
        second_result = AppointmentRankingService(self.tenant_id).finalize(
            case_id=second.id, ranking_no="RK-TIE-2"
        ).ranking

        self.assertEqual(first_result.rank_no, 1)
        self.assertEqual(first_result.outcome, AppointmentRankingResult.Outcome.SELECTED)
        self.assertEqual(second_result.rank_no, 2)
        self.assertEqual(second_result.outcome, AppointmentRankingResult.Outcome.WAITLIST)

    def test_missing_participant_result_fails_closed_without_partial_write(self):
        target, _, _ = self._participant("90")
        self._participant("80", with_result=False)

        with self.assertRaises(AppointmentRankingError) as ctx:
            AppointmentRankingService(self.tenant_id).finalize(
                case_id=target.id, ranking_no="RK-MISSING"
            )

        self.assertEqual(ctx.exception.code, "APPOINTMENT_ASSESSMENT_RESULT_REQUIRED")
        self.assertFalse(
            AppointmentRankingResult.objects.filter(ranking_no="RK-MISSING").exists()
        )

    def test_eligible_participant_cannot_be_silently_omitted_from_ranking(self):
        target, _, _ = self._participant("90")
        AppointmentApplicationCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=f"CASE-ELIGIBLE-{uuid.uuid4().hex[:8]}",
            person_id=uuid.uuid4(),
            policy_version_id=self.batch.policy_version_id,
            position_instance_id=target.position_instance_id,
            batch_no=self.batch.batch_no,
            requested_level_code="L2",
            status=AppointmentApplicationCase.Status.ELIGIBLE,
        )

        with self.assertRaises(AppointmentRankingError) as ctx:
            AppointmentRankingService(self.tenant_id).finalize(
                case_id=target.id, ranking_no="RK-INCOMPLETE-SCOPE"
            )

        self.assertEqual(
            ctx.exception.code, "APPOINTMENT_RANKING_PARTICIPANT_SCOPE_INCOMPLETE"
        )
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, AppointmentBatch.Status.REVIEWING)

    def test_service_rejects_client_forged_authority_fields(self):
        target, _, _ = self._participant("90")
        with self.assertRaises(AppointmentRankingError) as ctx:
            AppointmentRankingService(self.tenant_id).finalize(
                case_id=target.id,
                ranking_no="RK-FORGE",
                total_score="100",
                rank_no=1,
                outcome="SELECTED",
                score_snapshot={"forged": True},
            )
        self.assertEqual(
            ctx.exception.code, "APPOINTMENT_RANKING_CLIENT_AUTHORITY_FORBIDDEN"
        )

    def test_idempotent_replay_returns_same_fact_and_single_event(self):
        target, _, _ = self._participant("90")
        service = AppointmentRankingService(self.tenant_id)
        first = service.finalize(case_id=target.id, ranking_no="RK-REPLAY")
        replay = service.finalize(case_id=target.id, ranking_no="RK-REPLAY")

        self.assertFalse(replay.created)
        self.assertEqual(replay.ranking.id, first.ranking.id)
        self.assertEqual(
            HrOutboxEvent.objects.filter(
                tenant_id=self.tenant_id,
                event_type="hr.appointment.ranking.published",
            ).count(),
            1,
        )

    def test_cross_tenant_case_fails_closed(self):
        target, _, _ = self._participant("90")
        with self.assertRaises(AppointmentRankingError) as ctx:
            AppointmentRankingService(8).finalize(
                case_id=target.id, ranking_no="RK-CROSS-TENANT"
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_CASE_NOT_FOUND")

    def test_finalized_ranking_blocks_instance_queryset_and_delete_mutation(self):
        target, _, _ = self._participant("90")
        ranking = AppointmentRankingService(self.tenant_id).finalize(
            case_id=target.id, ranking_no="RK-SEALED"
        ).ranking
        ranking.rank_no = 9
        with self.assertRaisesRegex(ValueError, "APPOINTMENT_RANKING_IMMUTABLE"):
            ranking.save(update_fields=["rank_no", "updated_at"])
        with self.assertRaisesRegex(ValueError, "APPOINTMENT_RANKING_IMMUTABLE"):
            AppointmentRankingResult.objects.filter(pk=ranking.pk).update(rank_no=9)
        with self.assertRaisesRegex(ValueError, "APPOINTMENT_RANKING_IMMUTABLE"):
            AppointmentRankingResult.objects.filter(pk=ranking.pk).delete()
        with self.assertRaisesRegex(ValueError, "APPOINTMENT_RANKING_IMMUTABLE"):
            ranking.delete()
