import uuid
from decimal import Decimal

from django.test import TestCase

from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentBatch,
    AppointmentQuotaPool,
    AppointmentQuotaReservation,
    AppointmentRankingResult,
)
from hr_appointment.services.ranking_service import (
    AppointmentRankingError,
    AppointmentRankingService,
)


class Hr14RankingServiceTests(TestCase):
    def _batch(self, *, tenant_id=7, status=AppointmentBatch.Status.REVIEWING):
        return AppointmentBatch.objects.create(
            tenant_id=tenant_id,
            batch_no=f"BATCH-{tenant_id}-{uuid.uuid4().hex[:6]}",
            name="2026 岗位竞聘",
            policy_version_id=uuid.uuid4(),
            status=status,
        )

    def _case(self, batch, *, tenant_id=7, status=AppointmentApplicationCase.Status.UNDER_REVIEW):
        return AppointmentApplicationCase.objects.create(
            tenant_id=tenant_id,
            case_no=f"CASE-{tenant_id}-{uuid.uuid4().hex[:8]}",
            person_id=uuid.uuid4(),
            policy_version_id=batch.policy_version_id,
            position_instance_id=101,
            batch_no=batch.batch_no,
            requested_level_code="L2",
            status=status,
        )

    def _active_quota(self, batch, case, *, tenant_id=7):
        pool = AppointmentQuotaPool.objects.create(
            tenant_id=tenant_id,
            batch=batch,
            category_code="PROFESSIONAL",
            exact_level_code="L2",
            authorized=1,
            occupied=0,
            reserved=1,
        )
        reservation = AppointmentQuotaReservation.objects.create(
            tenant_id=tenant_id,
            quota_pool=pool,
            application_case=case,
            units=1,
            status=AppointmentQuotaReservation.Status.ACTIVE,
        )
        return pool, reservation

    def test_selected_ranking_is_append_only_fact_and_moves_case_to_proposed(self):
        batch = self._batch()
        case = self._case(batch)
        outcome = AppointmentRankingService(7, actor_user_id=88).finalize(
            case_id=case.id,
            ranking_no="RK-2026-0001",
            total_score="91.2500",
            rank_no=1,
            outcome="SELECTED",
            score_snapshot={"panel": "P1", "votes": 9},
        )

        self.assertTrue(outcome.created)
        self.assertEqual(outcome.ranking.total_score, Decimal("91.2500"))
        self.assertEqual(outcome.ranking.attempt_no, 1)
        case.refresh_from_db()
        self.assertEqual(case.status, AppointmentApplicationCase.Status.PROPOSED)

    def test_waitlist_moves_to_terminal_state_and_releases_active_quota(self):
        batch = self._batch(status=AppointmentBatch.Status.RANKING)
        case = self._case(batch)
        pool, reservation = self._active_quota(batch, case)

        outcome = AppointmentRankingService(7).finalize(
            case_id=case.id,
            ranking_no="RK-2026-0002",
            total_score="88.0000",
            rank_no=2,
            outcome="WAITLIST",
        )

        self.assertEqual(outcome.ranking.outcome, AppointmentRankingResult.Outcome.WAITLIST)
        case.refresh_from_db()
        pool.refresh_from_db()
        reservation.refresh_from_db()
        self.assertEqual(case.status, AppointmentApplicationCase.Status.WAITLIST)
        self.assertEqual(pool.reserved, 0)
        self.assertEqual(reservation.status, AppointmentQuotaReservation.Status.RELEASED)

    def test_not_selected_moves_to_terminal_state_without_quota(self):
        batch = self._batch(status=AppointmentBatch.Status.RANKING)
        case = self._case(batch)

        AppointmentRankingService(7).finalize(
            case_id=case.id,
            ranking_no="RK-2026-0002-N",
            total_score="70.0000",
            rank_no=5,
            outcome="NOT_SELECTED",
        )

        case.refresh_from_db()
        self.assertEqual(case.status, AppointmentApplicationCase.Status.NOT_SELECTED)

    def test_non_selected_case_with_consumed_quota_fails_closed_and_rolls_back_ranking(self):
        batch = self._batch(status=AppointmentBatch.Status.RANKING)
        case = self._case(batch)
        pool, reservation = self._active_quota(batch, case)
        pool.reserved = 0
        pool.occupied = 1
        pool.save(update_fields=["reserved", "occupied", "updated_at"])
        reservation.status = AppointmentQuotaReservation.Status.CONSUMED
        reservation.save(update_fields=["status", "updated_at"])

        with self.assertRaises(AppointmentRankingError) as ctx:
            AppointmentRankingService(7).finalize(
                case_id=case.id,
                ranking_no="RK-CORRUPT-CONSUMED",
                total_score="70.0000",
                rank_no=5,
                outcome="NOT_SELECTED",
            )

        self.assertEqual(ctx.exception.code, "APPOINTMENT_RANKING_QUOTA_ALREADY_CONSUMED")
        case.refresh_from_db()
        self.assertEqual(case.status, AppointmentApplicationCase.Status.UNDER_REVIEW)
        self.assertFalse(
            AppointmentRankingResult.objects.filter(
                tenant_id=7,
                ranking_no="RK-CORRUPT-CONSUMED",
            ).exists()
        )

    def test_batch_state_gate_blocks_ranking_outside_review_window(self):
        batch = self._batch(status=AppointmentBatch.Status.APPLICATION_OPEN)
        case = self._case(batch)
        with self.assertRaises(AppointmentRankingError) as ctx:
            AppointmentRankingService(7).finalize(
                case_id=case.id,
                ranking_no="RK-2026-0003",
                total_score="80",
                rank_no=3,
                outcome="NOT_SELECTED",
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_RANKING_INVALID_BATCH_STATE")
        self.assertFalse(
            AppointmentRankingResult.objects.filter(
                tenant_id=7, application_case_id=case.id
            ).exists()
        )

    def test_ranking_no_is_idempotent_but_conflicting_replay_is_rejected(self):
        batch = self._batch()
        case = self._case(batch)
        service = AppointmentRankingService(7)
        first = service.finalize(
            case_id=case.id,
            ranking_no="RK-2026-0004",
            total_score="90",
            rank_no=1,
            outcome="SELECTED",
        )
        replay = service.finalize(
            case_id=case.id,
            ranking_no="RK-2026-0004",
            total_score="90.0000",
            rank_no=1,
            outcome="SELECTED",
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.ranking.id, first.ranking.id)

        with self.assertRaises(AppointmentRankingError) as ctx:
            service.finalize(
                case_id=case.id,
                ranking_no="RK-2026-0004",
                total_score="89",
                rank_no=2,
                outcome="WAITLIST",
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_RANKING_IDEMPOTENCY_CONFLICT")

    def test_cross_tenant_case_fails_closed(self):
        batch = self._batch(tenant_id=8)
        case = self._case(batch, tenant_id=8)
        with self.assertRaises(AppointmentRankingError) as ctx:
            AppointmentRankingService(7).finalize(
                case_id=case.id,
                ranking_no="RK-2026-0005",
                total_score="85",
                rank_no=1,
                outcome="SELECTED",
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_CASE_NOT_FOUND")

    def test_finalized_ranking_fact_is_immutable(self):
        batch = self._batch()
        case = self._case(batch)
        ranking = AppointmentRankingService(7).finalize(
            case_id=case.id,
            ranking_no="RK-2026-0006",
            total_score="85",
            rank_no=1,
            outcome="WAITLIST",
        ).ranking
        ranking.rank_no = 9
        with self.assertRaisesRegex(ValueError, "APPOINTMENT_RANKING_IMMUTABLE"):
            ranking.save(update_fields=["rank_no", "updated_at"])
