import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from hr_appointment.models import AppointmentApplicationCase, AppointmentBatch
from hr_appointment.services.ranking_service import AppointmentRankingService


class AppointmentRankingBatchStateTests(TestCase):
    def test_first_finalized_ranking_moves_reviewing_batch_to_ranking(self):
        batch = AppointmentBatch.objects.create(
            tenant_id=7,
            batch_no="B-RANK-PROGRESS",
            name="2026 岗位竞聘",
            policy_version_id=uuid.uuid4(),
            status=AppointmentBatch.Status.REVIEWING,
        )
        case = AppointmentApplicationCase.objects.create(
            tenant_id=7,
            case_no="CASE-RANK-PROGRESS",
            person_id=uuid.uuid4(),
            policy_version_id=batch.policy_version_id,
            position_instance_id=101,
            batch_no=batch.batch_no,
            requested_level_code="L2",
            status=AppointmentApplicationCase.Status.UNDER_REVIEW,
        )

        with patch.object(
            AppointmentRankingService,
            "_derive_authority",
            return_value=SimpleNamespace(
                total_score=Decimal("91.2500"),
                rank_no=1,
                outcome="SELECTED",
                score_snapshot={"contentHash": "a" * 64},
            ),
        ), patch.object(AppointmentRankingService, "_emit_event"):
            AppointmentRankingService(7, actor_user_id=88).finalize(
                case_id=case.id,
                ranking_no="RK-PROGRESS-1",
            )

        batch.refresh_from_db()
        case.refresh_from_db()
        self.assertEqual(batch.status, AppointmentBatch.Status.RANKING)
        self.assertEqual(case.status, AppointmentApplicationCase.Status.PROPOSED)
