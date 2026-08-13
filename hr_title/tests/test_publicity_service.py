import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from hr_title.models import (
    TitleAppealRecord,
    TitleApplicationCase,
    TitlePublicityRecord,
)
from hr_title.services.publicity_service import TitlePublicityError, TitlePublicityService
from hr_title.services.result_service import ProfessionalTitleResultService, TitleResultError


class TitlePublicityServiceTests(TestCase):
    tenant_id = 77

    def _case(self, status=TitleApplicationCase.Status.PROPOSED):
        return TitleApplicationCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=f"CASE-{uuid.uuid4().hex[:10]}",
            person_id=uuid.uuid4(),
            policy_version_id=uuid.uuid4(),
            batch_no="2026-A",
            requested_title_code="ASSOCIATE_PROFESSOR",
            requested_title_name="副教授",
            status=status,
        )

    def _closed_window(self):
        now = timezone.now()
        return now - timedelta(days=2), now - timedelta(days=1)

    def test_open_publicity_creates_authority_and_moves_case(self):
        case = self._case()
        start = timezone.now()
        end = start + timedelta(days=5)
        publicity = TitlePublicityService(self.tenant_id, actor_user_id=9).open_publicity(
            case_id=case.id,
            publicity_no="PUB-001",
            start_at=start,
            end_at=end,
            content_snapshot={"title": "副教授拟通过"},
        )
        case.refresh_from_db()
        self.assertEqual(publicity.status, TitlePublicityRecord.Status.OPEN)
        self.assertEqual(case.status, TitleApplicationCase.Status.PUBLICITY)
        self.assertEqual(publicity.content_snapshot_json["title"], "副教授拟通过")

    def test_publicity_cannot_close_before_end(self):
        case = self._case()
        start = timezone.now()
        publicity = TitlePublicityService(self.tenant_id).open_publicity(
            case_id=case.id,
            publicity_no="PUB-002",
            start_at=start,
            end_at=start + timedelta(days=1),
        )
        with self.assertRaisesRegex(TitlePublicityError, "before end_at"):
            TitlePublicityService(self.tenant_id).close_publicity(publicity.id)

    def test_pending_appeal_blocks_publicity_close(self):
        case = self._case()
        start, end = self._closed_window()
        publicity = TitlePublicityRecord.objects.create(
            tenant_id=self.tenant_id,
            publicity_no="PUB-003",
            application_case_id=case.id,
            start_at=start,
            end_at=end,
            status=TitlePublicityRecord.Status.OPEN,
        )
        case.status = TitleApplicationCase.Status.PUBLICITY
        case.save(update_fields=["status", "updated_at"])
        TitleAppealRecord.objects.create(
            tenant_id=self.tenant_id,
            appeal_no="APL-003",
            publicity_id=publicity.id,
            application_case_id=case.id,
            reason="材料真实性异议",
            status=TitleAppealRecord.Status.OPEN,
        )
        with self.assertRaisesRegex(TitlePublicityError, "all appeals must be resolved"):
            TitlePublicityService(self.tenant_id).close_publicity(publicity.id)

    def test_upheld_appeal_blocks_publicity_close(self):
        case = self._case()
        start, end = self._closed_window()
        publicity = TitlePublicityRecord.objects.create(
            tenant_id=self.tenant_id,
            publicity_no="PUB-004",
            application_case_id=case.id,
            start_at=start,
            end_at=end,
            status=TitlePublicityRecord.Status.OPEN,
        )
        TitleAppealRecord.objects.create(
            tenant_id=self.tenant_id,
            appeal_no="APL-004",
            publicity_id=publicity.id,
            application_case_id=case.id,
            reason="评审程序异议",
            status=TitleAppealRecord.Status.UPHELD,
            resolution="复核确认程序存在问题",
        )
        with self.assertRaisesRegex(TitlePublicityError, "upheld appeal"):
            TitlePublicityService(self.tenant_id).close_publicity(publicity.id)

    def test_rejected_appeal_allows_publicity_close_after_end(self):
        case = self._case()
        start, end = self._closed_window()
        publicity = TitlePublicityRecord.objects.create(
            tenant_id=self.tenant_id,
            publicity_no="PUB-005",
            application_case_id=case.id,
            start_at=start,
            end_at=end,
            status=TitlePublicityRecord.Status.OPEN,
        )
        TitleAppealRecord.objects.create(
            tenant_id=self.tenant_id,
            appeal_no="APL-005",
            publicity_id=publicity.id,
            application_case_id=case.id,
            reason="结果异议",
            status=TitleAppealRecord.Status.REJECTED,
            resolution="复核后不成立",
        )
        closed = TitlePublicityService(self.tenant_id, actor_user_id=9).close_publicity(publicity.id)
        self.assertEqual(closed.status, TitlePublicityRecord.Status.CLOSED)
        self.assertIsNotNone(closed.closed_at)

    def test_formal_result_gate_rejects_publicity_state_without_real_record(self):
        case = self._case(status=TitleApplicationCase.Status.PUBLICITY)
        with self.assertRaisesRegex(TitleResultError, "real publicity record is required"):
            ProfessionalTitleResultService(self.tenant_id)._require_closed_publicity(case)

    def test_formal_result_gate_rejects_upheld_appeal_even_on_closed_record(self):
        case = self._case(status=TitleApplicationCase.Status.PUBLICITY)
        start, end = self._closed_window()
        publicity = TitlePublicityRecord.objects.create(
            tenant_id=self.tenant_id,
            publicity_no="PUB-006",
            application_case_id=case.id,
            start_at=start,
            end_at=end,
            status=TitlePublicityRecord.Status.CLOSED,
            closed_at=timezone.now(),
        )
        TitleAppealRecord.objects.create(
            tenant_id=self.tenant_id,
            appeal_no="APL-006",
            publicity_id=publicity.id,
            application_case_id=case.id,
            reason="成立异议",
            status=TitleAppealRecord.Status.UPHELD,
            resolution="成立",
        )
        with self.assertRaisesRegex(TitleResultError, "upheld appeal"):
            ProfessionalTitleResultService(self.tenant_id)._require_closed_publicity(case)
