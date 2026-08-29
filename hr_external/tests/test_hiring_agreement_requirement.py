"""Focused regression coverage for HR08 agreement requirement routing."""

from datetime import date

from django.test import TestCase

from hr_external.constants import (
    AgreementProviderStatus,
    AgreementRequirement,
    ExternalHiringStatus,
)
from hr_external.models import HrExternalHiringCase
from hr_external.services.category_service import CategoryService
from hr_external.services.hiring_service import HiringService
from hr_external.services.profile_service import ProfileService
from hr_staff.models import HrPerson


class HiringAgreementRequirementTests(TestCase):
    def setUp(self):
        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(
            tenant_id=self.tenant,
            legal_name="协议策略回归教师",
        )
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="INDUSTRY_PROFESSOR",
        )
        self.category = self.profile.primary_category
        self.service = HiringService()

    def _case(self, suffix: str) -> HrExternalHiringCase:
        return HrExternalHiringCase.objects.create(
            tenant_id=self.tenant,
            case_no=f"C-AGR-{suffix}",
            request_org_id=1,
            requester_id=1,
            category_id=self.category,
            purpose="协议策略回归",
            proposed_person_id=self.person,
            requested_start=date(2026, 9, 1),
            requested_end=date(2027, 8, 31),
            planned_assignments_json=[
                {"assignmentType": "TEACHING", "organizationId": 1}
            ],
            status=ExternalHiringStatus.APPROVED,
        )

    def _set_requirement(self, requirement: str) -> None:
        self.category.agreement_requirement = requirement
        self.category.save(update_fields=["agreement_requirement", "updated_at"])

    def test_required_before_activation_still_waits_for_signed_agreement(self):
        self._set_requirement(AgreementRequirement.REQUIRED_BEFORE_ACTIVATION)
        case = self._case("BEFORE")

        self.service.wait_agreement(case)

        case.refresh_from_db()
        self.assertEqual(case.status, ExternalHiringStatus.WAITING_AGREEMENT)

    def test_not_required_skips_agreement_wait_and_records_not_required(self):
        self._set_requirement(AgreementRequirement.NOT_REQUIRED)
        case = self._case("NONE")

        self.service.wait_agreement(case)
        case.refresh_from_db()
        self.assertEqual(case.status, ExternalHiringStatus.READY_TO_ACTIVATE)

        engagement = self.service.activate(case)

        self.assertEqual(engagement.agreement_requirement, AgreementRequirement.NOT_REQUIRED)
        self.assertEqual(
            engagement.agreement_status,
            AgreementProviderStatus.NOT_REQUIRED,
        )
        self.assertEqual(engagement.agreement_id, "")
        case.refresh_from_db()
        self.assertEqual(case.status, ExternalHiringStatus.ACTIVATED)

    def test_grace_period_skips_wait_but_keeps_agreement_pending(self):
        self._set_requirement(AgreementRequirement.REQUIRED_AFTER_ACTIVATION_GRACE)
        case = self._case("GRACE")

        self.service.wait_agreement(case)
        case.refresh_from_db()
        self.assertEqual(case.status, ExternalHiringStatus.READY_TO_ACTIVATE)

        engagement = self.service.activate(case)

        self.assertEqual(
            engagement.agreement_requirement,
            AgreementRequirement.REQUIRED_AFTER_ACTIVATION_GRACE,
        )
        self.assertEqual(
            engagement.agreement_status,
            AgreementProviderStatus.UNAVAILABLE,
        )
        self.assertEqual(engagement.agreement_id, "")
        case.refresh_from_db()
        self.assertEqual(case.status, ExternalHiringStatus.ACTIVATED)
