from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from hr_recruitment.constants import (
    ApplicationCanonicalStatus,
    CampaignStatus,
    CandidateStatus,
)
from hr_recruitment.models import (
    HrApplicationMaterial,
    HrJobApplication,
    HrRecruitmentAuditEvent,
    HrRecruitmentCampaign,
    HrRecruitmentCandidate,
    HrRecruitmentPosition,
)
from hr_recruitment.services.retention_service import CandidateRetentionService


class CandidateRetentionServiceTests(TestCase):
    def setUp(self):
        self.tenant_id = 7
        self.campaign = HrRecruitmentCampaign.objects.create(
            tenant_id=self.tenant_id,
            code="2026-R1",
            title="2026 年公开招聘",
            status=CampaignStatus.CLOSED,
        )
        self.position = HrRecruitmentPosition.objects.create(
            tenant_id=self.tenant_id,
            campaign_id=self.campaign,
            post_catalog_name="专任教师",
            public_slug="teacher",
            status="CLOSED",
        )

    def _candidate(self, suffix="1", **overrides):
        values = {
            "tenant_id": self.tenant_id,
            "candidate_uid": f"c-retention-{suffix}",
            "candidate_no": f"CAN-{suffix}",
            "legal_name": "张三",
            "primary_email": f"candidate{suffix}@example.edu.cn",
            "primary_mobile": "13800138000",
            "national_id_hash": "a" * 64,
            "retention_until": timezone.localdate() - timedelta(days=1),
        }
        values.update(overrides)
        return HrRecruitmentCandidate.objects.create(**values)

    def _application(self, candidate, status):
        return HrJobApplication.objects.create(
            tenant_id=self.tenant_id,
            candidate_id=candidate,
            recruitment_position_id=self.position,
            canonical_status=status,
            form_snapshot={"statement": "含个人信息的报名说明"},
        )

    @patch("hr_recruitment.services.retention_service.delete_application_material")
    def test_terminal_candidate_is_anonymized_with_material_and_audit(self, delete):
        candidate = self._candidate()
        application = self._application(
            candidate, ApplicationCanonicalStatus.WITHDRAWN
        )
        material = HrApplicationMaterial.objects.create(
            tenant_id=self.tenant_id,
            application_id=application,
            title="个人简历",
            file_name="resume.pdf",
            file_path=f"protected/hr04/{self.tenant_id}/{application.id}/file.pdf",
            sha256="b" * 64,
            mime_type="application/pdf",
            file_size_bytes=100,
            retention_until=candidate.retention_until,
        )

        outcome = CandidateRetentionService(self.tenant_id).anonymize_if_due(
            candidate.id
        )

        self.assertEqual(outcome.status, "anonymized")
        self.assertEqual(outcome.materials_purged, 1)
        delete.assert_called_once()
        candidate.refresh_from_db()
        application.refresh_from_db()
        material.refresh_from_db()
        self.assertEqual(candidate.status, CandidateStatus.ANONYMIZED)
        self.assertEqual(candidate.legal_name, "已匿名化")
        self.assertEqual(candidate.primary_email, "")
        self.assertEqual(candidate.primary_mobile, "")
        self.assertEqual(candidate.national_id_hash, "")
        self.assertIsNotNone(candidate.anonymized_at)
        self.assertEqual(application.form_snapshot, {})
        self.assertEqual(material.file_path, "")
        self.assertEqual(material.file_size_bytes, 0)
        self.assertIsNotNone(material.purged_at)
        self.assertTrue(
            HrRecruitmentAuditEvent.objects.filter(
                tenant_id=self.tenant_id,
                business_object_id=str(candidate.id),
                event_type="CANDIDATE_RETENTION_ANONYMIZED",
            ).exists()
        )

    @patch("hr_recruitment.services.retention_service.delete_application_material")
    def test_active_workflow_is_never_anonymized(self, delete):
        candidate = self._candidate("2")
        self._application(candidate, ApplicationCanonicalStatus.SUBMITTED)

        outcome = CandidateRetentionService(self.tenant_id).anonymize_if_due(
            candidate.id
        )

        self.assertEqual(outcome.status, "active_workflow")
        delete.assert_not_called()
        candidate.refresh_from_db()
        self.assertEqual(candidate.status, CandidateStatus.ACTIVE)
        self.assertEqual(candidate.legal_name, "张三")

    def test_legal_hold_requires_reason_and_blocks_expiry(self):
        candidate = self._candidate("3")
        service = CandidateRetentionService(self.tenant_id, actor="42")
        service.set_legal_hold(candidate.id, enabled=True, reason="劳动争议案件留存")

        outcome = service.anonymize_if_due(candidate.id)

        self.assertEqual(outcome.status, "legal_hold")
        candidate.refresh_from_db()
        self.assertTrue(candidate.legal_hold)
        self.assertEqual(candidate.legal_hold_reason, "劳动争议案件留存")
        self.assertTrue(
            HrRecruitmentAuditEvent.objects.filter(
                business_object_id=str(candidate.id),
                event_type="CANDIDATE_LEGAL_HOLD_CHANGED",
            ).exists()
        )
