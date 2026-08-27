"""W-B production DB chain: HR08 external hiring -> HR07 agreement -> HR08 activation.

The contract proves an external worker can use the shared HrPerson identity root
without fabricating HrStaffMaster or HrEmploymentRelationship facts.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from hr_contracts.models import HrContractAgreement, HrContractVersion
from hr_contracts.services.agreement_service import AgreementService
from hr_external.constants import (
    AgreementProviderStatus,
    EthicsReviewStatus,
    ExternalEngagementStatus,
    ExternalHiringStatus,
)
from hr_external.integrations.hr07 import AgreementProvider
from hr_external.models import (
    HrExternalEngagementAssignment,
    HrExternalEthicsReview,
    HrExternalHiringCase,
    HrExternalLifecycleEvent,
)
from hr_external.services.category_service import CategoryService
from hr_external.services.hiring_service import AgreementNotReady, HiringService
from hr_external.services.profile_service import ProfileService
from hr_staff.models import HrEmploymentRelationship, HrPerson, HrStaffMaster


TENANT = 8208


class WBExternalAgreementActivationChainTests(TestCase):
    def setUp(self):
        today = date.today()
        CategoryService().ensure_default_categories(TENANT)
        self.person = HrPerson.objects.create(
            tenant_id=TENANT,
            legal_name="W-B 外聘教师",
        )
        self.profile = ProfileService().create_profile(
            tenant_id=TENANT,
            person_id=self.person.id,
            primary_category_code="INDUSTRY_PROFESSOR",
            source_organization_name="W-B 产业合作单位",
        )
        self.profile.identity_verification_status = "VERIFIED"
        self.profile.ethics_status = "PASS"
        self.profile.save(
            update_fields=["identity_verification_status", "ethics_status", "updated_at"]
        )
        self.category = self.profile.primary_category
        self.category.agreement_type_code = "EXTERNAL_WORKFORCE"
        self.category.save(update_fields=["agreement_type_code", "updated_at"])

        self.case = HrExternalHiringCase.objects.create(
            tenant_id=TENANT,
            case_no="WB-EXT-001",
            request_org_id=820801,
            requester_id=1,
            category_id=self.category,
            purpose="W-B 外聘教学与产业指导",
            proposed_person_id=self.person,
            requested_start=today,
            requested_end=today + timedelta(days=365),
            planned_assignments_json=[
                {
                    "assignmentType": "TEACHING",
                    "roleTitle": "产业兼职教师",
                    "organizationId": 820801,
                }
            ],
            status=ExternalHiringStatus.DRAFT,
        )
        HrExternalEthicsReview.objects.create(
            tenant_id=TENANT,
            person_id=self.person,
            case_id=self.case,
            review_type="HIRING",
            status=EthicsReviewStatus.PASS,
            reviewer=1,
            reviewed_at=timezone.now(),
        )
        self.hiring = HiringService()

    def _approve_to_waiting_agreement(self):
        self.hiring.submit(self.case)
        self.hiring.college_approve(self.case)
        self.hiring.hr_approve(self.case)
        self.hiring.school_approve(self.case)
        self.hiring.wait_agreement(self.case)
        self.assertEqual(self.case.status, ExternalHiringStatus.WAITING_AGREEMENT)

    def test_external_person_contract_activates_without_shadow_employee(self):
        today = date.today()
        self._approve_to_waiting_agreement()

        agreement_service = AgreementService(TENANT, actor_user_id=1)
        agreement = agreement_service.create_external_agreement(
            agreement_no="WB-EXT-CONTRACT-001",
            person_id=self.person.id,
            subject_reference_type="HR08_HIRING_CASE",
            subject_reference_id=str(self.case.id),
            agreement_title="W-B 外聘教师合作协议",
            agreement_type=self.category.agreement_type_code,
        )
        replay = agreement_service.create_external_agreement(
            agreement_no="WB-EXT-CONTRACT-001",
            person_id=self.person.id,
            subject_reference_type="HR08_HIRING_CASE",
            subject_reference_id=str(self.case.id),
            agreement_title="W-B 外聘教师合作协议",
            agreement_type=self.category.agreement_type_code,
        )
        self.assertEqual(replay.id, agreement.id)
        self.assertEqual(
            agreement.subject_type,
            HrContractAgreement.SubjectType.EXTERNAL_WORKFORCE,
        )
        self.assertEqual(agreement.subject_person_id, self.person.id)
        self.assertIsNone(agreement.staff_id)
        self.assertIsNone(agreement.employment_relationship_id)

        signed = agreement_service.sign_initial_version(
            agreement_id=agreement.id,
            effective_from=today,
            effective_to=today + timedelta(days=365),
            signed_at=timezone.now(),
            signed_document_ref="private://contracts/wb-external-001.pdf",
            content_snapshot={
                "personId": str(self.person.id),
                "hiringCaseId": str(self.case.id),
                "workerKind": "EXTERNAL",
            },
            source_business_type="HR08_HIRING_CASE",
            source_business_id=str(self.case.id),
        )
        effective = agreement_service.activate_initial_version(
            agreement_id=agreement.id,
            version_id=signed.id,
            as_of=today,
        )
        agreement.refresh_from_db()
        effective.refresh_from_db()
        self.assertEqual(agreement.status, HrContractAgreement.Status.ACTIVE)
        self.assertEqual(effective.status, HrContractVersion.Status.EFFECTIVE)

        provider = AgreementProvider()
        wrong_tenant = provider.resolve_agreement(
            tenant_id=TENANT + 1,
            agreement_type_code=self.category.agreement_type_code,
            agreement_id=str(agreement.id),
            subject_reference_type="HR08_HIRING_CASE",
            subject_reference_id=str(self.case.id),
        )
        self.assertFalse(wrong_tenant.is_available)
        self.assertEqual(
            provider.agreement_status_code(wrong_tenant),
            AgreementProviderStatus.UNAVAILABLE.value,
        )

        other_case = HrExternalHiringCase.objects.create(
            tenant_id=TENANT,
            case_no="WB-EXT-002",
            request_org_id=820802,
            requester_id=1,
            category_id=self.category,
            purpose="other case must not steal agreement",
            proposed_person_id=self.person,
            requested_start=today,
            requested_end=today + timedelta(days=30),
            status=ExternalHiringStatus.WAITING_AGREEMENT,
        )
        with self.assertRaises(AgreementNotReady):
            self.hiring.confirm_agreement(
                other_case,
                agreement_id=str(agreement.id),
            )

        ready = self.hiring.confirm_agreement(
            self.case,
            agreement_id=str(agreement.id),
        )
        self.assertEqual(ready.status, ExternalHiringStatus.READY_TO_ACTIVATE)
        self.assertEqual(ready.agreement_id, str(agreement.id))

        engagement = self.hiring.activate(ready, actor_id=1)
        ready.refresh_from_db()
        self.assertEqual(ready.status, ExternalHiringStatus.ACTIVATED)
        self.assertEqual(engagement.status, ExternalEngagementStatus.ACTIVE)
        self.assertEqual(engagement.person_id_id, self.person.id)
        self.assertEqual(engagement.agreement_id, str(agreement.id))
        self.assertEqual(
            engagement.agreement_status,
            AgreementProviderStatus.ACTIVE.value,
        )
        self.assertTrue(
            HrExternalEngagementAssignment.objects.filter(
                tenant_id=TENANT,
                engagement_id=engagement,
            ).exists()
        )
        self.assertTrue(
            HrExternalLifecycleEvent.objects.filter(
                tenant_id=TENANT,
                event_type="ExternalEngagementActivated",
                engagement_id=engagement,
            ).exists()
        )

        # Production red line: external workforce shares Person identity only.
        self.assertEqual(HrPerson.objects.filter(tenant_id=TENANT).count(), 1)
        self.assertEqual(HrStaffMaster.objects.filter(tenant_id=TENANT).count(), 0)
        self.assertEqual(
            HrEmploymentRelationship.objects.filter(tenant_id=TENANT).count(),
            0,
        )
