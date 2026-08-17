import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from hr_title.models import TitleApplicationCase
from hr_title.services.publicity_service import TitlePublicityError, TitlePublicityService


class TitlePublicityHardeningTests(TestCase):
    tenant_id = 77

    def _case(self):
        return TitleApplicationCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=f"CASE-{uuid.uuid4().hex[:10]}",
            person_id=uuid.uuid4(),
            policy_version_id=uuid.uuid4(),
            batch_no="2026-A",
            requested_title_code="ASSOCIATE_PROFESSOR",
            requested_title_name="副教授",
            status=TitleApplicationCase.Status.PROPOSED,
        )

    def test_appeal_before_publicity_start_is_rejected(self):
        case = self._case()
        now = timezone.now()
        publicity = TitlePublicityService(self.tenant_id).open_publicity(
            case_id=case.id,
            publicity_no="PUB-WINDOW-1",
            start_at=now + timedelta(hours=1),
            end_at=now + timedelta(days=3),
        )
        with self.assertRaisesRegex(TitlePublicityError, "within the publicity window"):
            TitlePublicityService(self.tenant_id).lodge_appeal(
                publicity_id=publicity.id,
                appeal_no="APL-WINDOW-1",
                reason="程序异议",
                now=now,
            )

    def test_publicity_number_retry_is_idempotent(self):
        case = self._case()
        start = timezone.now()
        end = start + timedelta(days=3)
        service = TitlePublicityService(self.tenant_id, actor_user_id=9)
        first = service.open_publicity(
            case_id=case.id,
            publicity_no="PUB-IDEM-1",
            start_at=start,
            end_at=end,
            content_snapshot={"title": "拟通过"},
        )
        second = service.open_publicity(
            case_id=case.id,
            publicity_no="PUB-IDEM-1",
            start_at=start,
            end_at=end,
            content_snapshot={"title": "拟通过"},
        )
        self.assertEqual(first.id, second.id)

    def test_publicity_number_conflict_is_rejected(self):
        case = self._case()
        start = timezone.now()
        end = start + timedelta(days=3)
        service = TitlePublicityService(self.tenant_id)
        service.open_publicity(
            case_id=case.id,
            publicity_no="PUB-IDEM-2",
            start_at=start,
            end_at=end,
            content_snapshot={"title": "拟通过"},
        )
        with self.assertRaisesRegex(TitlePublicityError, "different content"):
            service.open_publicity(
                case_id=case.id,
                publicity_no="PUB-IDEM-2",
                start_at=start,
                end_at=end,
                content_snapshot={"title": "被篡改"},
            )

    def test_appeal_number_retry_is_idempotent(self):
        case = self._case()
        now = timezone.now()
        service = TitlePublicityService(self.tenant_id)
        publicity = service.open_publicity(
            case_id=case.id,
            publicity_no="PUB-IDEM-3",
            start_at=now - timedelta(hours=1),
            end_at=now + timedelta(days=2),
        )
        first = service.lodge_appeal(
            publicity_id=publicity.id,
            appeal_no="APL-IDEM-1",
            reason="材料真实性异议",
            appellant_ref="teacher-1",
            evidence={"file": "F-1"},
            now=now,
        )
        second = service.lodge_appeal(
            publicity_id=publicity.id,
            appeal_no="APL-IDEM-1",
            reason="材料真实性异议",
            appellant_ref="teacher-1",
            evidence={"file": "F-1"},
            now=now,
        )
        self.assertEqual(first.id, second.id)

    def test_non_object_snapshots_and_evidence_are_rejected(self):
        case = self._case()
        now = timezone.now()
        service = TitlePublicityService(self.tenant_id)
        with self.assertRaisesRegex(TitlePublicityError, "content_snapshot must be an object"):
            service.open_publicity(
                case_id=case.id,
                publicity_no="PUB-INVALID-1",
                start_at=now,
                end_at=now + timedelta(days=2),
                content_snapshot=["not", "an", "object"],
            )
        publicity = service.open_publicity(
            case_id=case.id,
            publicity_no="PUB-INVALID-2",
            start_at=now - timedelta(hours=1),
            end_at=now + timedelta(days=2),
        )
        with self.assertRaisesRegex(TitlePublicityError, "evidence must be an object"):
            service.lodge_appeal(
                publicity_id=publicity.id,
                appeal_no="APL-INVALID-1",
                reason="程序异议",
                evidence=["bad"],
                now=now,
            )
