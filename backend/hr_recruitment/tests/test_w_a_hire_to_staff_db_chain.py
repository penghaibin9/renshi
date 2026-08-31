"""W-A cross-domain production contract: HR02 -> HR04 -> HR05 -> HR03.

This test deliberately does not replay every internal recruitment decision that
HR04 already covers in its own suites.  Instead it locks the cross-domain
Authority boundaries that previously had no real-database acceptance:

- HR02 creates the organization, catalog, position and HELD reservation through
  canonical services;
- HR04 hands an accepted hire to the real HR05 consumer exactly once;
- handoff leaves capacity HELD (HR04 must not commit it early);
- HR05 Activation runs the real HR03 Person/Staff/Employment/Assignment writers;
- only after those facts exist does HR05 commit HR02 HELD -> COMMITTED;
- activation replay creates no duplicate HR03 facts;
- a different tenant cannot inspect or activate the case.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from hr_onboarding.api.exceptions import TenantContextRequiredError
from hr_onboarding.constants import CaseStatus, PersonMatchStatus
from hr_onboarding.models import HrOnboardingCase
from hr_onboarding.services.activation_service import ActivationService
from hr_onboarding.services.case_service import CaseService
from hr_onboarding.services.report_service import ReportService
from hr_recruitment.constants import (
    ApplicationCanonicalStatus as ApplicationStatus,
    HandoffStatus,
    OfferStatus,
    PublicNoticeStatus,
)
from hr_recruitment.integrations.hr05 import Hr05OnboardingConsumer
from hr_recruitment.models import (
    HrProposedHire,
    HrPublicNotice,
    HrPublicNoticeEntry,
    HrRecruitmentOffer,
)
from hr_recruitment.services.application_service import ApplicationService
from hr_recruitment.services.campaign_service import CampaignService
from hr_recruitment.services.candidate_service import CandidateService
from hr_recruitment.services.handoff_service import HandoffService
from hr_staff.models import (
    HrEmploymentRelationship,
    HrPerson,
    HrStaffAssignment,
    HrStaffMaster,
)
from hr_structure.models import HrPositionReservation
from hr_structure.scope import Hr02Scope
from hr_structure.services.organization_change import OrganizationChangeService
from hr_structure.services.position import PositionService
from hr_structure.services.post_catalog import PostCatalogService

TENANT = 8121


class WAHireToStaffDatabaseChainTests(TestCase):
    def setUp(self):
        self.today = date.today()
        self.scope = Hr02Scope("SCHOOL", tenant_id=TENANT)

        org_service = OrganizationChangeService(self.scope, actor="w-a")
        self.school = org_service.create_organization(
            stable_code="WA-SCHOOL",
            name="W-A 大学",
            org_type="SCHOOL",
            dimension="ADMIN",
            validity_from=self.today,
        )
        self.college = org_service.create_organization(
            stable_code="WA-COLLEGE",
            name="W-A 学院",
            org_type="COLLEGE",
            dimension="ADMIN",
            parent_id=self.school.id,
            validity_from=self.today,
        )

        self.catalog = PostCatalogService(self.scope, actor="w-a").create_catalog(
            stable_code="WA-TEACHER",
            name="专任教师",
            category="PROFESSIONAL_TECHNICAL",
            subcategory="TEACHER",
            validity_from=self.today,
        )
        self.catalog_version = self.catalog.versions.get(status="ACTIVE")

        self.position_service = PositionService(self.scope, actor="w-a")
        self.hr02_position = self.position_service.create_position(
            position_code="WA-POS-001",
            organization_id=self.college.id,
            post_catalog_version_id=self.catalog_version.id,
            max_incumbents=1,
            validity_from=self.today,
        )

        campaign_service = CampaignService(tenant_id=TENANT, actor="w-a")
        self.campaign = campaign_service.create_campaign(
            code="WA-2026-001",
            title="W-A 招聘链验收",
            campaign_type="SINGLE_POSITION",
        )
        self.recruitment_position = campaign_service.create_position(
            campaign_id=str(self.campaign.id),
            organization_id=self.college.id,
            organization_name="W-A 学院",
            post_catalog_id=self.catalog.id,
            post_catalog_name="专任教师",
            position_id=self.hr02_position.id,
            planned_headcount=1,
            min_hires=1,
            max_hires=1,
        )
        # Canonical HR04 -> HR02 reservation path, not a direct fixture insert.
        self.recruitment_position = campaign_service.make_ready(
            str(self.recruitment_position.id)
        )
        self.reservation = HrPositionReservation.objects.get(
            tenant_id=TENANT,
            id=int(self.recruitment_position.reservation_id),
        )
        self.assertEqual(self.reservation.status, HrPositionReservation.Status.HELD)

        candidate = CandidateService(tenant_id=TENANT).create_candidate(
            legal_name="W-A 张三",
            primary_email="wa-hire@example.invalid",
        )
        application_service = ApplicationService(tenant_id=TENANT, actor="w-a")
        application = application_service.save_draft(
            candidate_id=str(candidate.id),
            recruitment_position_id=str(self.recruitment_position.id),
            form_data={"degree": "博士"},
        )
        self.application = application_service.submit(application_id=str(application.id))
        # The intra-HR04 qualification/assessment/offer state machines are covered
        # by their dedicated suites.  This cross-domain fixture starts at the
        # authoritative accepted-hire boundary.
        self.application.canonical_status = ApplicationStatus.OFFER_ACCEPTED
        self.application.save(update_fields=["canonical_status"])

        self.proposed = HrProposedHire.objects.create(
            tenant_id=TENANT,
            application_id=self.application,
            recruitment_position_id=self.recruitment_position,
            rank=1,
            final_score=90,
            reservation_id=str(self.reservation.id),
            reservation_no=self.reservation.reservation_no,
            approval_status="APPROVE",
            approved_by="w-a",
            approved_at=timezone.now(),
            created_by="w-a",
        )
        notice = HrPublicNotice.objects.create(
            tenant_id=TENANT,
            campaign_id=self.campaign,
            notice_no="WA-NOTICE-001",
            start_at=timezone.now() - timedelta(days=2),
            end_at=timezone.now() - timedelta(days=1),
            published_at=timezone.now() - timedelta(days=2),
            status=PublicNoticeStatus.CLOSED_NO_BLOCKER,
            published_by="w-a",
        )
        HrPublicNoticeEntry.objects.create(
            tenant_id=TENANT,
            notice_id=notice,
            proposed_hire_id=self.proposed,
            public_display_name="W-A 张**",
            public_fields_json={"岗位": "专任教师"},
        )
        HrRecruitmentOffer.objects.create(
            tenant_id=TENANT,
            proposed_hire_id=self.proposed,
            offer_no="WA-OFFER-001",
            issued_at=timezone.now() - timedelta(days=1),
            status=OfferStatus.ACCEPTED,
            accepted_at=timezone.now(),
            employment_type="FULL_TIME",
            expected_report_date=self.today,
            created_by="w-a",
        )

    def _handoff_to_hr05(self) -> HrOnboardingCase:
        handoff = HandoffService(tenant_id=TENANT, actor="w-a").handoff(
            proposed_hire_id=str(self.proposed.id),
            idempotency_key="wa-handoff-001",
            hr05_consumer=Hr05OnboardingConsumer(),
        )
        self.assertEqual(handoff.status, HandoffStatus.CREATED)
        self.assertTrue(handoff.hr05_case_id)

        # Replaying the HR04 command must point at the same handoff/case.
        replay = HandoffService(tenant_id=TENANT, actor="w-a").handoff(
            proposed_hire_id=str(self.proposed.id),
            idempotency_key="wa-handoff-replay",
            hr05_consumer=Hr05OnboardingConsumer(),
        )
        self.assertEqual(replay.id, handoff.id)
        self.assertEqual(replay.hr05_case_id, handoff.hr05_case_id)

        case = HrOnboardingCase.objects.get(
            tenant_id=TENANT,
            id=handoff.hr05_case_id,
        )
        self.assertEqual(case.planned_organization_id_id, self.college.id)
        self.assertEqual(case.planned_post_catalog_id_id, self.catalog.id)
        self.assertEqual(case.planned_position_id_id, self.hr02_position.id)
        self.assertEqual(case.position_reservation_id_id, self.reservation.id)

        # HR04 handoff must not consume capacity.  Activation owns the commit.
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, HrPositionReservation.Status.HELD)
        return case

    def _ready_for_activation(self, case: HrOnboardingCase) -> HrOnboardingCase:
        service = CaseService(tenant_id=TENANT)
        case = service.confirm_intent(case)
        service._transition_locked(
            case,
            CaseStatus.READY_TO_REPORT,
            "WA_TEST",
            "W-A 准备报到",
        )
        ReportService(tenant_id=TENANT).confirm_report(
            case,
            actual_report_at=timezone.now() - timedelta(hours=1),
            checked_identity=True,
        )
        case.refresh_from_db()
        service._transition_locked(case, CaseStatus.VERIFYING, "WA_TEST", "W-A 材料核验")
        service._transition_locked(
            case,
            CaseStatus.READY_FOR_ACTIVATION,
            "WA_TEST",
            "W-A 准备激活",
        )
        case = service.resolve_person_match(
            case,
            person_id=None,
            status=PersonMatchStatus.EXACT_MATCH,
        )
        case.refresh_from_db()
        return case

    def test_real_handoff_activation_commits_capacity_after_hr03_facts(self):
        case = self._ready_for_activation(self._handoff_to_hr05())
        activation = ActivationService(tenant_id=TENANT)

        gate = activation.gate(case, effective_at=self.today)
        self.assertTrue(gate.passed, [item.code for item in gate.items if not item.ok])

        result = activation.activate(
            case,
            effective_at=self.today,
            idempotency_key="wa-activate-001",
        )
        self.assertTrue(result["activated"], result)

        # Real HR03 Authority facts must exist before HR02 is marked committed.
        person = HrPerson.objects.get(tenant_id=TENANT, id=result["person_id"])
        staff = HrStaffMaster.objects.get(tenant_id=TENANT, id=result["staff_master_id"])
        employment = HrEmploymentRelationship.objects.get(
            tenant_id=TENANT,
            id=result["employment_id"],
        )
        assignment = HrStaffAssignment.objects.get(
            tenant_id=TENANT,
            id=result["assignment_id"],
        )
        self.assertEqual(staff.person_id_id, person.id)
        self.assertEqual(employment.staff_id_id, staff.id)
        self.assertEqual(assignment.employment_relationship_id_id, employment.id)
        self.assertEqual(assignment.organization_id_id, self.college.id)
        self.assertEqual(assignment.position_id_id, self.hr02_position.id)
        self.assertEqual(assignment.post_catalog_id_id, self.catalog_version.id)

        self.reservation.refresh_from_db()
        self.assertEqual(
            self.reservation.status,
            HrPositionReservation.Status.COMMITTED,
        )

        # Same activation is idempotent: no second Person/Staff/Employment/Assignment.
        replay = activation.activate(
            HrOnboardingCase.objects.get(tenant_id=TENANT, id=case.id),
            effective_at=self.today,
            idempotency_key="wa-activate-001",
        )
        self.assertEqual(replay["staff_master_id"], result["staff_master_id"])
        self.assertEqual(HrPerson.objects.filter(tenant_id=TENANT).count(), 1)
        self.assertEqual(HrStaffMaster.objects.filter(tenant_id=TENANT).count(), 1)
        self.assertEqual(HrEmploymentRelationship.objects.filter(tenant_id=TENANT).count(), 1)
        self.assertEqual(HrStaffAssignment.objects.filter(tenant_id=TENANT).count(), 1)

    def test_activation_fails_closed_for_wrong_tenant(self):
        case = self._ready_for_activation(self._handoff_to_hr05())
        with self.assertRaises(TenantContextRequiredError):
            ActivationService(tenant_id=TENANT + 1).gate(
                case,
                effective_at=self.today,
            )
        with self.assertRaises(TenantContextRequiredError):
            ActivationService(tenant_id=TENANT + 1).activate(
                case,
                effective_at=self.today,
                idempotency_key="wa-cross-tenant",
            )

        # Failed cross-tenant attempt must not consume the HR02 reservation.
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, HrPositionReservation.Status.HELD)
