import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentBatch,
    AppointmentPublicityObjection,
    AppointmentPublicityRecord,
    AppointmentRankingResult,
)
from hr_appointment.services.publicity_service import (
    AppointmentPublicityError,
    AppointmentPublicityService,
)


class Hr14PublicityServiceTests(TestCase):
    def _batch(
        self,
        *,
        tenant_id=7,
        status=AppointmentBatch.Status.RANKING,
        frozen_window=True,
    ):
        now = timezone.now()
        return AppointmentBatch.objects.create(
            tenant_id=tenant_id,
            batch_no=f"B-{tenant_id}-{uuid.uuid4().hex[:6]}",
            name="2026 岗位竞聘",
            policy_version_id=uuid.uuid4(),
            publicity_from=now - timedelta(hours=1) if frozen_window else None,
            publicity_to=now + timedelta(days=5) if frozen_window else None,
            status=status,
        )

    def _selected_case(self, batch, *, tenant_id=7):
        case = AppointmentApplicationCase.objects.create(
            tenant_id=tenant_id,
            case_no=f"C-{tenant_id}-{uuid.uuid4().hex[:8]}",
            person_id=uuid.uuid4(),
            policy_version_id=batch.policy_version_id,
            position_instance_id=101,
            batch_no=batch.batch_no,
            requested_level_code="L2",
            status=AppointmentApplicationCase.Status.PROPOSED,
        )
        ranking = AppointmentRankingResult.objects.create(
            tenant_id=tenant_id,
            ranking_no=f"R-{tenant_id}-{uuid.uuid4().hex[:8]}",
            application_case_id=case.id,
            batch_no=batch.batch_no,
            position_instance_id=case.position_instance_id,
            attempt_no=1,
            total_score=Decimal("91.2500"),
            rank_no=1,
            outcome=AppointmentRankingResult.Outcome.SELECTED,
            score_snapshot_json={"panel": "P1"},
        )
        return case, ranking

    def _review_case(self, batch, *, suffix: str, position_id: int):
        return AppointmentApplicationCase.objects.create(
            tenant_id=7,
            case_no=f"C-{suffix}-{uuid.uuid4().hex[:6]}",
            person_id=uuid.uuid4(),
            policy_version_id=batch.policy_version_id,
            position_instance_id=position_id,
            batch_no=batch.batch_no,
            requested_level_code="L2",
            status=AppointmentApplicationCase.Status.UNDER_REVIEW,
        )

    def _open(self, *, tenant_id=7, batch_status=AppointmentBatch.Status.RANKING):
        batch = self._batch(tenant_id=tenant_id, status=batch_status)
        case, ranking = self._selected_case(batch, tenant_id=tenant_id)
        now = timezone.now()
        record = AppointmentPublicityService(tenant_id, actor_user_id=88).open_publicity(
            case_id=case.id,
            ranking_result_id=ranking.id,
            publicity_no=f"P-{tenant_id}-{uuid.uuid4().hex[:8]}",
            start_at=batch.publicity_from,
            end_at=batch.publicity_to,
            notice_snapshot={"rank": 1, "position": 101},
        ).publicity
        return batch, case, ranking, record, now

    def test_open_publicity_consumes_frozen_window_and_moves_case_and_batch(self):
        batch, case, ranking, record, _ = self._open()
        frozen_from = batch.publicity_from
        frozen_to = batch.publicity_to

        case.refresh_from_db()
        batch.refresh_from_db()
        self.assertEqual(case.status, AppointmentApplicationCase.Status.PUBLICITY)
        self.assertEqual(batch.status, AppointmentBatch.Status.PUBLICITY)
        self.assertEqual(batch.publicity_from, frozen_from)
        self.assertEqual(batch.publicity_to, frozen_to)
        self.assertEqual(record.start_at, frozen_from)
        self.assertEqual(record.end_at, frozen_to)
        self.assertEqual(record.ranking_result_id, ranking.id)
        self.assertEqual(record.status, AppointmentPublicityRecord.Status.OPEN)

    def test_open_publicity_rejects_missing_or_mismatched_frozen_window(self):
        missing = self._batch(frozen_window=False)
        case, ranking = self._selected_case(missing)
        now = timezone.now()
        with self.assertRaises(AppointmentPublicityError) as ctx:
            AppointmentPublicityService(7).open_publicity(
                case_id=case.id,
                ranking_result_id=ranking.id,
                publicity_no="P-NO-WINDOW",
                start_at=now,
                end_at=now + timedelta(days=5),
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_PUBLICITY_BATCH_WINDOW_REQUIRED")

        batch = self._batch()
        case, ranking = self._selected_case(batch)
        with self.assertRaises(AppointmentPublicityError) as ctx:
            AppointmentPublicityService(7).open_publicity(
                case_id=case.id,
                ranking_result_id=ranking.id,
                publicity_no="P-MISMATCH",
                start_at=batch.publicity_from + timedelta(minutes=1),
                end_at=batch.publicity_to,
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_PUBLICITY_BATCH_WINDOW_MISMATCH")

    def test_open_publicity_blocks_while_another_case_is_still_under_review(self):
        batch = self._batch()
        case, ranking = self._selected_case(batch)
        AppointmentApplicationCase.objects.create(
            tenant_id=7,
            case_no="C-PENDING",
            person_id=uuid.uuid4(),
            policy_version_id=batch.policy_version_id,
            position_instance_id=102,
            batch_no=batch.batch_no,
            status=AppointmentApplicationCase.Status.UNDER_REVIEW,
        )

        with self.assertRaises(AppointmentPublicityError) as ctx:
            AppointmentPublicityService(7).open_publicity(
                case_id=case.id,
                ranking_result_id=ranking.id,
                publicity_no="P-BLOCKED",
                start_at=batch.publicity_from,
                end_at=batch.publicity_to,
            )

        self.assertEqual(ctx.exception.code, "APPOINTMENT_BATCH_RANKING_INCOMPLETE")
        case.refresh_from_db()
        self.assertEqual(case.status, AppointmentApplicationCase.Status.PROPOSED)

    def test_ranked_waitlist_and_not_selected_cases_do_not_deadlock_publicity(self):
        batch = self._batch()
        selected = self._review_case(batch, suffix="SELECTED", position_id=101)
        waitlist = self._review_case(batch, suffix="WAITLIST", position_id=101)
        not_selected = self._review_case(batch, suffix="NO", position_id=101)
        selected_ranking = AppointmentRankingResult.objects.create(
            tenant_id=7,
            ranking_no="RK-MULTI-1",
            application_case_id=selected.id,
            batch_no=batch.batch_no,
            position_instance_id=selected.position_instance_id,
            attempt_no=1,
            total_score="92",
            rank_no=1,
            outcome="SELECTED",
            score_snapshot_json={"source": "sealed-assessment-test"},
        )
        selected.status = AppointmentApplicationCase.Status.PROPOSED
        selected.save(update_fields=["status", "updated_at"])
        waitlist.status = AppointmentApplicationCase.Status.WAITLIST
        waitlist.save(update_fields=["status", "updated_at"])
        not_selected.status = AppointmentApplicationCase.Status.NOT_SELECTED
        not_selected.save(update_fields=["status", "updated_at"])

        record = AppointmentPublicityService(7, actor_user_id=88).open_publicity(
            case_id=selected.id,
            ranking_result_id=selected_ranking.id,
            publicity_no="P-MULTI-RANKED",
            start_at=batch.publicity_from,
            end_at=batch.publicity_to,
        ).publicity

        selected.refresh_from_db()
        waitlist.refresh_from_db()
        not_selected.refresh_from_db()
        self.assertEqual(record.status, AppointmentPublicityRecord.Status.OPEN)
        self.assertEqual(selected.status, AppointmentApplicationCase.Status.PUBLICITY)
        self.assertEqual(waitlist.status, AppointmentApplicationCase.Status.WAITLIST)
        self.assertEqual(not_selected.status, AppointmentApplicationCase.Status.NOT_SELECTED)
        self.assertFalse(
            AppointmentApplicationCase.objects.filter(
                tenant_id=7,
                batch_no=batch.batch_no,
                status=AppointmentApplicationCase.Status.UNDER_REVIEW,
            ).exists()
        )

    def test_objection_is_only_accepted_inside_open_publicity_window(self):
        _, _, _, record, now = self._open()
        service = AppointmentPublicityService(7, actor_user_id=88)
        objection = service.submit_objection(
            publicity_id=record.id,
            objection_no="OBJ-001",
            content_summary="排序材料存在事实错误",
            submitter_ref="STAFF-9",
            evidence_refs=["file:evidence-1"],
            now=now,
        )
        self.assertEqual(objection.status, AppointmentPublicityObjection.Status.RECEIVED)

        with self.assertRaises(AppointmentPublicityError) as ctx:
            service.submit_objection(
                publicity_id=record.id,
                objection_no="OBJ-002",
                content_summary="逾期异议",
                now=record.end_at + timedelta(seconds=1),
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_OBJECTION_OUTSIDE_WINDOW")

    def test_publicity_cannot_close_before_window_end_or_with_pending_objection(self):
        _, _, _, record, now = self._open()
        service = AppointmentPublicityService(7, actor_user_id=88)
        with self.assertRaises(AppointmentPublicityError) as ctx:
            service.close_publicity(record.id, now=now)
        self.assertEqual(ctx.exception.code, "APPOINTMENT_PUBLICITY_WINDOW_NOT_ENDED")

        service.submit_objection(
            publicity_id=record.id,
            objection_no="OBJ-003",
            content_summary="需要核查",
            now=now,
        )
        with self.assertRaises(AppointmentPublicityError) as ctx:
            service.close_publicity(record.id, now=record.end_at + timedelta(seconds=1))
        self.assertEqual(ctx.exception.code, "APPOINTMENT_PUBLICITY_OBJECTION_PENDING")

    def test_upheld_objection_blocks_close_and_requires_cancel_correction(self):
        _, case, _, record, now = self._open()
        service = AppointmentPublicityService(7, actor_user_id=88)
        objection = service.submit_objection(
            publicity_id=record.id,
            objection_no="OBJ-004",
            content_summary="公示信息有误",
            now=now,
        )
        service.resolve_objection(
            objection.id,
            outcome="UPHELD",
            resolution_note="核查属实，需要更正拟聘信息",
        )

        with self.assertRaises(AppointmentPublicityError) as ctx:
            service.close_publicity(record.id, now=record.end_at + timedelta(seconds=1))
        self.assertEqual(ctx.exception.code, "APPOINTMENT_PUBLICITY_UPHELD_OBJECTION")

        service.cancel_publicity(record.id, reason="异议成立，退回拟聘更正")
        case.refresh_from_db()
        record.refresh_from_db()
        self.assertEqual(case.status, AppointmentApplicationCase.Status.PROPOSED)
        self.assertEqual(record.status, AppointmentPublicityRecord.Status.CANCELLED)

    def test_resolved_not_upheld_objection_allows_close_and_effect_gate(self):
        _, case, _, record, now = self._open()
        service = AppointmentPublicityService(7, actor_user_id=88)
        objection = service.submit_objection(
            publicity_id=record.id,
            objection_no="OBJ-005",
            content_summary="质疑评分",
            now=now,
        )
        service.resolve_objection(
            objection.id,
            outcome="NOT_UPHELD",
            resolution_note="复核原始评分与表决记录无误",
        )
        closed = service.close_publicity(
            record.id, now=record.end_at + timedelta(seconds=1)
        )

        self.assertEqual(closed.status, AppointmentPublicityRecord.Status.CLOSED)
        ready = service.assert_ready_for_effect(case.id)
        self.assertEqual(ready.id, record.id)

    def test_open_publicity_is_tenant_scoped(self):
        batch = self._batch(tenant_id=8)
        case, ranking = self._selected_case(batch, tenant_id=8)
        with self.assertRaises(AppointmentPublicityError) as ctx:
            AppointmentPublicityService(7).open_publicity(
                case_id=case.id,
                ranking_result_id=ranking.id,
                publicity_no="P-XTENANT",
                start_at=batch.publicity_from,
                end_at=batch.publicity_to,
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_CASE_NOT_FOUND")
