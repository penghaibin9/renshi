from datetime import date
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from hr10_development.constants import MilestoneType, VerificationStatus
from hr10_development.models import (
    HrDevelopmentAuditEvent,
    HrDevelopmentOutboxEvent,
    HrFurtherStudyCase,
    HrFurtherStudyMilestone,
)
from hr10_development.providers.base import ProviderResult, ProviderStatus
from hr10_development.providers.education_writeback_provider import (
    Hr03EducationWritebackProvider,
)
from hr10_development.services.further_study_service import (
    FurtherStudyService,
    FurtherStudyVerificationError,
    FurtherStudyWritebackError,
    validate_writeback_evidence,
)


TENANT = 71


def graduation_evidence():
    return {
        "school_name": "示范大学",
        "education_level": "硕士研究生",
        "degree_name": "工学硕士",
        "major_name": "计算机科学",
        "diploma_document_id": "doc-diploma-1",
    }


def certificate_evidence():
    return {
        "credential_type": "PROFESSIONAL_CERTIFICATE",
        "credential_name": "数据治理专业证书",
        "credential_no": "CERT-2026-0001",
        "issuing_authority": "行业协会",
        "certificate_document_id": "doc-certificate-1",
    }


class FurtherStudyWritebackContractTests(SimpleTestCase):
    def test_service_uses_real_provider_and_case_staff_master_id(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "services"
            / "further_study_service.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Hr03EducationWritebackProvider", source)
        self.assertIn("staff_master_id=str(case.staff_master_id)", source)
        self.assertNotIn("StubEducationWritebackProvider", source)
        self.assertNotIn('staff_master_id=str(getattr(milestone, "case_id"', source)

    def test_unverified_or_incomplete_evidence_cannot_formalize(self):
        milestone = type(
            "Milestone",
            (),
            {
                "milestone_type": MilestoneType.GRADUATED,
                "actual_date": date(2026, 6, 30),
            },
        )()
        with self.assertRaises(FurtherStudyVerificationError):
            validate_writeback_evidence(milestone, {"school_name": "A"})
        with self.assertRaises(FurtherStudyVerificationError):
            validate_writeback_evidence(
                milestone,
                {"education_level": "硕士", "document_id": "doc-1"},
            )

    def test_real_provider_contract_never_returns_unavailable(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "providers"
            / "education_writeback_provider.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("ProviderStatus.UNAVAILABLE", source)
        self.assertIn("BackgroundService", source)
        self.assertIn("legacy_employee_id", source)

    def test_migration_marks_legacy_verified_without_receipt_as_failed(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0024_hrfurtherstudymilestone_writeback_at_and_more.py"
        ).read_text(encoding="utf-8")
        self.assertIn("LEGACY_FALSE_SUCCESS", migration)
        self.assertIn('status="WRITEBACK_FAILED"', migration)
        self.assertIn('writeback_status="FAILED"', migration)


class RecordingProvider:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or ProviderResult(
            ProviderStatus.OK,
            {"education_id": "edu-1", "degree_id": "degree-1"},
        )

    def submit_education_record(self, tenant_id, staff_master_id, education_data):
        self.calls.append((tenant_id, staff_master_id, education_data))
        return self.result


class FurtherStudyWritebackServiceTests(TestCase):
    def setUp(self):
        self.case = HrFurtherStudyCase.objects.create(
            tenant_id=TENANT,
            staff_master_id=99001,
            study_type="DEGREE",
            field_or_major="计算机科学",
            start_date=date(2023, 9, 1),
            planned_end_date=date(2026, 6, 30),
        )
        self.milestone = HrFurtherStudyMilestone.objects.create(
            tenant_id=TENANT,
            case_id=self.case.id,
            milestone_type=MilestoneType.GRADUATED,
            planned_date=date(2026, 6, 30),
            actual_date=date(2026, 6, 28),
        )

    def test_success_uses_case_staff_id_and_is_idempotent(self):
        provider = RecordingProvider()
        result = FurtherStudyService.verify_milestone(
            self.milestone,
            VerificationStatus.DOCUMENT_VERIFIED,
            graduation_evidence(),
            education_provider=provider,
        )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(provider.calls[0][1], str(self.case.staff_master_id))
        self.assertNotEqual(provider.calls[0][1], str(self.case.id))
        self.milestone.refresh_from_db()
        self.assertEqual(self.milestone.writeback_status, "SUCCEEDED")
        self.assertEqual(self.milestone.writeback_refs["education_id"], "edu-1")
        self.assertEqual(HrDevelopmentAuditEvent.objects.count(), 1)
        self.assertEqual(HrDevelopmentOutboxEvent.objects.count(), 1)

        replay = FurtherStudyService.verify_milestone(
            self.milestone,
            VerificationStatus.DOCUMENT_VERIFIED,
            graduation_evidence(),
            education_provider=provider,
        )
        self.assertEqual(replay["status"], "ALREADY_VERIFIED")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(HrDevelopmentOutboxEvent.objects.count(), 1)

    def test_provider_error_rolls_back_milestone_audit_and_event(self):
        provider = RecordingProvider(
            ProviderResult(ProviderStatus.ERROR, None, "HR03 unavailable")
        )
        with self.assertRaises(FurtherStudyWritebackError):
            FurtherStudyService.verify_milestone(
                self.milestone,
                VerificationStatus.DOCUMENT_VERIFIED,
                graduation_evidence(),
                education_provider=provider,
            )
        self.milestone.refresh_from_db()
        self.assertEqual(self.milestone.status, "PENDING")
        self.assertNotEqual(self.milestone.verification_status, "UNAVAILABLE")
        self.assertEqual(HrDevelopmentAuditEvent.objects.count(), 0)
        self.assertEqual(HrDevelopmentOutboxEvent.objects.count(), 0)

    def test_untrusted_status_and_cross_tenant_parent_fail_closed(self):
        with self.assertRaises(FurtherStudyVerificationError):
            FurtherStudyService.verify_milestone(
                self.milestone,
                VerificationStatus.SELF_REPORTED,
                graduation_evidence(),
                education_provider=RecordingProvider(),
            )

        other = HrFurtherStudyMilestone.objects.create(
            tenant_id=TENANT + 1,
            case_id=self.case.id,
            milestone_type=MilestoneType.GRADUATED,
            planned_date=date(2026, 6, 30),
            actual_date=date(2026, 6, 30),
        )
        with self.assertRaises(FurtherStudyVerificationError):
            FurtherStudyService.verify_milestone(
                other,
                VerificationStatus.DOCUMENT_VERIFIED,
                graduation_evidence(),
                education_provider=RecordingProvider(),
            )


class Hr03EducationWritebackProviderTests(TestCase):
    def setUp(self):
        from hr_staff.tests.factories import make_person, make_staff

        self.staff = make_staff(TENANT, make_person(TENANT, "进修教师"), "FS-001")
        self.staff.legacy_employee_id = 99001
        self.staff.save(update_fields=["legacy_employee_id", "updated_at"])
        self.provider = Hr03EducationWritebackProvider()

    def _payload(self, milestone_type, evidence, source_id):
        return {
            "milestone_type": milestone_type,
            "source_business_id": source_id,
            "actual_date": date(2026, 6, 28),
            "start_date": date(2023, 9, 1),
            "field_or_major": "计算机科学",
            "full_time_or_part_time": "FULL_TIME",
            "evidence": evidence,
        }

    def test_graduation_writes_verified_education_and_degree_once(self):
        from hr_staff.models import HrDegreeRecord, HrEducationExperience

        payload = self._payload(MilestoneType.GRADUATED, graduation_evidence(), "FS:101")
        first = self.provider.submit_education_record(TENANT, "99001", payload)
        second = self.provider.submit_education_record(TENANT, "99001", payload)
        self.assertIs(first.status, ProviderStatus.OK)
        self.assertIs(second.status, ProviderStatus.OK)
        self.assertTrue(second.data["replayed"])
        self.assertEqual(HrEducationExperience.objects.count(), 1)
        self.assertEqual(HrDegreeRecord.objects.count(), 1)
        education = HrEducationExperience.objects.get()
        degree = HrDegreeRecord.objects.get()
        self.assertEqual(education.staff_id, self.staff)
        self.assertEqual(education.verification_status, "VERIFIED")
        self.assertEqual(degree.verification_status, "VERIFIED")

    def test_certificate_writes_verified_credential_once(self):
        from hr_staff.models import HrCredential

        payload = self._payload(
            MilestoneType.CERTIFICATE_RECEIVED,
            certificate_evidence(),
            "FS:102",
        )
        first = self.provider.submit_education_record(TENANT, "99001", payload)
        second = self.provider.submit_education_record(TENANT, "99001", payload)
        self.assertIs(first.status, ProviderStatus.OK)
        self.assertTrue(second.data["replayed"])
        self.assertEqual(HrCredential.objects.count(), 1)
        credential = HrCredential.objects.get()
        self.assertEqual(credential.staff_id, self.staff)
        self.assertEqual(credential.verification_status, "VERIFIED")
        self.assertNotIn("CERT-2026-0001", credential.credential_no_masked)

    def test_cross_tenant_staff_reference_returns_explicit_error(self):
        result = self.provider.submit_education_record(
            TENANT + 1,
            "99001",
            self._payload(MilestoneType.GRADUATED, graduation_evidence(), "FS:103"),
        )
        self.assertIs(result.status, ProviderStatus.ERROR)
        self.assertIn("CROSS_TENANT", result.error_message)
