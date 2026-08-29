"""W-A continuation contract: HR03 active staff -> HR07 contract -> HR06 change.

The first W-A database test proves HR02 -> HR04 -> HR05 -> HR03 activation.  This
continuation deliberately starts from the same canonical HR03 Authority shape
and proves that downstream domains consume it without shadow writes:

- HR07 creates, freezes and activates a contract bound to the HR03 staff and
  active employment relationship;
- HR06 creates/submits/approves a real organization+position transfer;
- HR06 reserves target capacity in HR02, switches the HR03 primary assignment,
  then commits that reservation;
- the original HR07 signed contract remains immutable and a formal HR07 review
  follow-up is recorded instead of silently rewriting the contract.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from hr_changes.constants import CaseStatus, ChangeActionCode, DownstreamEffectStatus
from hr_changes.integrations.hr02 import PositionGate
from hr_changes.models import HrChangeDownstreamEffect, HrChangeEffectiveSnapshot
from hr_changes.services.apply_service import ApplyService
from hr_changes.services.change_service import ChangeService
from hr_changes.tests.factories import make_action, make_org, make_position, make_reason
from hr_contracts.models import HrContractAgreement, HrContractVersion
from hr_contracts.services.agreement_service import AgreementService
from hr_staff.models import HrStaffAssignment
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.services.person_identity_service import PersonIdentityService
from hr_staff.services.staff_master_service import StaffMasterService
from hr_structure.models import HrPositionReservation

TENANT = 8122
FIXTURE_SOURCE = "MIGRATION_VERIFIED"


class WAStaffContractChangeChainTests(TestCase):
    def setUp(self):
        self.today = date.today()
        historical_start = self.today - timedelta(days=365)

        self.source_org = make_org(
            TENANT,
            "WA-SOURCE-ORG",
            "W-A 原学院",
            historical_start,
        )
        self.target_org = make_org(
            TENANT,
            "WA-TARGET-ORG",
            "W-A 新学院",
            historical_start,
        )
        self.source_position = make_position(
            TENANT,
            self.source_org,
            "WA-SOURCE-POS",
            max_incumbents=1,
            validity_from=historical_start,
        )
        self.target_position = make_position(
            TENANT,
            self.target_org,
            "WA-TARGET-POS",
            max_incumbents=1,
            validity_from=historical_start,
        )

        self.person = PersonIdentityService().create_person_with_identity(
            tenant_id=TENANT,
            legal_name="W-A 李老师",
        )
        self.staff = StaffMasterService().create_staff(
            tenant_id=TENANT,
            person_id=self.person.id,
            staff_category_code="TEACHER",
            source="BUSINESS_PROCESS",
        )
        self.relationship = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            employment_type="FULL_TIME",
            effective_from=historical_start,
            source_business_type="HR05_ONBOARDING",
            source_business_id="wa-upstream-activation",
            reason_code="ONBOARDING",
        )
        self.source_assignment = AssignmentService(TENANT).create_assignment(
            employment_relationship_id=self.relationship,
            assignment_type="PRIMARY",
            effective_from=historical_start,
            organization_id=self.source_org,
            position_id=self.source_position,
            post_catalog_id=self.source_position.post_catalog_version_id,
            source_business_type=FIXTURE_SOURCE,
            source_business_id="wa-source-assignment",
        )

    def _activate_contract(self):
        service = AgreementService(TENANT, actor_user_id=1)
        agreement = service.create_agreement(
            agreement_no="WA-CONTRACT-001",
            staff_id=self.staff.id,
            employment_relationship_id=self.relationship.id,
            agreement_title="W-A 教师聘用合同",
            agreement_type="EMPLOYMENT",
            as_of=self.today,
        )
        signed = service.sign_initial_version(
            agreement_id=agreement.id,
            effective_from=self.today - timedelta(days=30),
            effective_to=self.today + timedelta(days=365),
            signed_at=timezone.now() - timedelta(days=30),
            signed_document_ref="private://contracts/wa-contract-001.pdf",
            content_snapshot={
                "staffNo": self.staff.staff_no,
                "employmentRelationshipId": str(self.relationship.id),
                "clauses": ["岗位聘用", "学校规章"],
            },
            source_business_type="HR05_ONBOARDING",
            source_business_id="wa-upstream-activation",
        )
        effective = service.activate_initial_version(
            agreement_id=agreement.id,
            version_id=signed.id,
            as_of=self.today,
        )
        agreement.refresh_from_db()
        effective.refresh_from_db()
        self.assertEqual(agreement.status, HrContractAgreement.Status.ACTIVE)
        self.assertEqual(effective.status, HrContractVersion.Status.EFFECTIVE)
        self.assertEqual(agreement.staff_id, self.staff.id)
        self.assertEqual(agreement.employment_relationship_id, self.relationship.id)
        return agreement, effective

    def _approved_transfer(self):
        action = make_action(TENANT, ChangeActionCode.ORG_POSITION_TRANSFER)
        reason = make_reason(TENANT, ChangeActionCode.ORG_POSITION_TRANSFER)
        service = ChangeService(TENANT, actor_user_id=1)
        case = service.create_case(
            staff_master_id=self.staff,
            action_id=action,
            reason_id=reason,
            requested_effective_at=self.today,
            proposals=[
                {
                    "domain": "assignment",
                    "field_code": "organization",
                    "old_value_ref": str(self.source_org.id),
                    "proposed_value_ref": str(self.target_org.id),
                },
                {
                    "domain": "assignment",
                    "field_code": "position",
                    "old_value_ref": str(self.source_position.id),
                    "proposed_value_ref": str(self.target_position.id),
                },
                {
                    "domain": "assignment",
                    "field_code": "post_catalog",
                    "old_value_ref": str(self.source_position.post_catalog_version_id_id),
                    "proposed_value_ref": str(self.target_position.post_catalog_version_id_id),
                },
            ],
            source_org_id=self.source_org,
            target_org_id=self.target_org,
            source_position_id=self.source_position,
            target_position_id=self.target_position,
            source_assignment_id=self.source_assignment,
        )
        case = service.submit(case.id)
        case = service.start_approval(case.id)
        case = service.approve_all(case.id)
        self.assertEqual(case.status, CaseStatus.APPROVED_WAITING_EFFECTIVE)

        reservation = PositionGate(TENANT).reserve_for_case(case)
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation.status, HrPositionReservation.Status.HELD)
        return case, reservation

    def test_active_contract_survives_real_hr06_transfer_with_review_followup(self):
        agreement, contract_version = self._activate_contract()
        original_hash = contract_version.content_hash
        original_snapshot = contract_version.content_snapshot_json

        case, reservation = self._approved_transfer()
        result = ApplyService(TENANT, actor_user_id=1).apply_case(
            case.id,
            effective_at=self.today,
            request_id="wa-transfer-001",
        )
        self.assertEqual(result.status, CaseStatus.EFFECTIVE)

        # HR03 Authority switched atomically: historical source segment is closed,
        # and the current primary points at the exact HR02 target org/position/catalog.
        self.source_assignment.refresh_from_db()
        self.assertEqual(self.source_assignment.status, "ENDED")
        self.assertEqual(self.source_assignment.effective_to, self.today)

        current = EffectiveDatedQueryService(TENANT).primary_assignment_as_of(
            self.staff.id,
            self.today,
        )
        self.assertIsNotNone(current)
        self.assertNotEqual(current.id, self.source_assignment.id)
        self.assertEqual(current.organization_id_id, self.target_org.id)
        self.assertEqual(current.position_id_id, self.target_position.id)
        self.assertEqual(
            current.post_catalog_id_id,
            self.target_position.post_catalog_version_id_id,
        )
        self.assertEqual(current.source_business_type, "HR06_TRANSFER")

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, HrPositionReservation.Status.COMMITTED)

        snapshot = HrChangeEffectiveSnapshot.objects.get(change_case_id=case)
        self.assertTrue(snapshot.checksum)
        self.assertEqual(snapshot.effective_at, self.today)
        self.assertEqual(
            snapshot.position_changes_json["target_position"],
            str(self.target_position.id),
        )

        # HR06 must not rewrite HR07's signed evidence.  It emits a formal review
        # follow-up so contract changes can run through HR07's own lifecycle.
        agreement.refresh_from_db()
        contract_version.refresh_from_db()
        self.assertEqual(agreement.status, HrContractAgreement.Status.ACTIVE)
        self.assertEqual(contract_version.status, HrContractVersion.Status.EFFECTIVE)
        self.assertEqual(contract_version.content_hash, original_hash)
        self.assertEqual(contract_version.content_snapshot_json, original_snapshot)
        self.assertEqual(agreement.staff_id, self.staff.id)
        self.assertEqual(agreement.employment_relationship_id, self.relationship.id)

        review = HrChangeDownstreamEffect.objects.get(
            change_case_id=case,
            target_domain="HR07",
            effect_type="ContractReviewRequired",
        )
        self.assertEqual(review.status, DownstreamEffectStatus.PENDING)

        # No shadow Staff/Relationship is created during contract or change flow.
        self.assertEqual(
            EffectiveDatedQueryService(TENANT)
            .relationships_as_of(self.staff.id, self.today)
            .count(),
            1,
        )
        self.assertEqual(
            HrStaffAssignment.objects.filter(
                tenant_id=TENANT,
                employment_relationship_id=self.relationship,
                assignment_type="PRIMARY",
            ).count(),
            2,
        )
