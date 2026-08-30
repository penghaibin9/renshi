"""One-person W-A production contract across HR02 -> HR04 -> HR05 -> HR03 -> HR07 -> HR06.

The existing W-A suites prove the upstream and downstream halves independently.
This test closes the acceptance gap by carrying the exact HR03 staff,
employment relationship, and primary assignment produced by HR05 activation into
HR07 contracting and HR06 organization+position transfer in the same tenant.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from hr_changes.constants import CaseStatus, ChangeActionCode, DownstreamEffectStatus
from hr_changes.integrations.hr02 import PositionGate
from hr_changes.models import HrChangeDownstreamEffect, HrChangeEffectiveSnapshot
from hr_changes.services.apply_service import ApplyService
from hr_changes.services.change_service import ChangeService
from hr_changes.tests.factories import make_action, make_reason
from hr_contracts.models import HrContractAgreement, HrContractVersion
from hr_contracts.services.agreement_service import AgreementService
from hr_onboarding.models import HrOnboardingCase
from hr_onboarding.services.activation_service import ActivationService
from hr_recruitment.integrations.hr05 import Hr05OnboardingConsumer
from hr_recruitment.services.handoff_service import HandoffService
from hr_recruitment.tests import test_w_a_hire_to_staff_db_chain as hire_chain_contract
from hr_staff.models import (
    HrEmploymentRelationship,
    HrPerson,
    HrStaffAssignment,
    HrStaffMaster,
)
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService
from hr_structure.models import HrPositionReservation
from hr_structure.services.organization_change import OrganizationChangeService
from hr_structure.services.post_catalog import PostCatalogService

TENANT = hire_chain_contract.TENANT


class WAFullHireContractChangeChainTests(TestCase):
    def test_same_hire_reaches_contract_and_change_without_shadow_identity(self):
        today = date.today()

        # 1) Reuse the canonical HR02/HR04 accepted-hire fixture, but execute a
        # fresh uniquely keyed HR04 -> HR05 handoff for this full-chain proof.
        upstream = hire_chain_contract.WAHireToStaffDatabaseChainTests(
            methodName="test_real_handoff_activation_commits_capacity_after_hr03_facts"
        )
        upstream.setUp()
        handoff = HandoffService(
            tenant_id=hire_chain_contract.TENANT,
            actor="w-a-full-chain",
        ).handoff(
            proposed_hire_id=str(upstream.proposed.id),
            idempotency_key=f"wa-full-handoff-{uuid.uuid4().hex}",
            hr05_consumer=Hr05OnboardingConsumer(),
        )
        self.assertTrue(handoff.hr05_case_id)
        onboarding_case = HrOnboardingCase.objects.get(
            tenant_id=hire_chain_contract.TENANT,
            id=handoff.hr05_case_id,
        )

        # 2) HR05 activates the exact hire into HR03 Authority facts. The source
        # HR02 reservation may become COMMITTED only after these facts exist.
        onboarding_case = upstream._ready_for_activation(onboarding_case)
        activation = ActivationService(tenant_id=hire_chain_contract.TENANT).activate(
            onboarding_case,
            effective_at=today,
            idempotency_key=f"wa-full-activate-{uuid.uuid4().hex}",
        )
        self.assertTrue(activation["activated"], activation)

        staff = HrStaffMaster.objects.get(
            tenant_id=hire_chain_contract.TENANT,
            id=activation["staff_master_id"],
        )
        relationship = HrEmploymentRelationship.objects.get(
            tenant_id=hire_chain_contract.TENANT,
            id=activation["employment_id"],
        )
        source_assignment = HrStaffAssignment.objects.get(
            tenant_id=hire_chain_contract.TENANT,
            id=activation["assignment_id"],
        )
        person = HrPerson.objects.get(
            tenant_id=hire_chain_contract.TENANT,
            id=activation["person_id"],
        )

        self.assertEqual(staff.person_id_id, person.id)
        self.assertEqual(relationship.staff_id_id, staff.id)
        self.assertEqual(
            source_assignment.employment_relationship_id_id,
            relationship.id,
        )
        self.assertEqual(source_assignment.organization_id_id, upstream.college.id)
        self.assertEqual(source_assignment.position_id_id, upstream.hr02_position.id)

        upstream.reservation.refresh_from_db()
        self.assertEqual(
            upstream.reservation.status,
            HrPositionReservation.Status.COMMITTED,
        )

        # 3) HR07 signs a real contract against the exact HR03 staff and
        # relationship created above. The source id points back to this HR05 case.
        agreement_service = AgreementService(
            hire_chain_contract.TENANT,
            actor_user_id=1,
        )
        agreement = agreement_service.create_agreement(
            agreement_no="WA-FULL-CONTRACT-001",
            staff_id=staff.id,
            employment_relationship_id=relationship.id,
            agreement_title="W-A 全链教师聘用合同",
            agreement_type="EMPLOYMENT",
            as_of=today,
        )
        signed = agreement_service.sign_initial_version(
            agreement_id=agreement.id,
            effective_from=today,
            effective_to=today + timedelta(days=365),
            signed_at=timezone.now(),
            signed_document_ref="private://contracts/wa-full-contract-001.pdf",
            content_snapshot={
                "staffNo": staff.staff_no,
                "employmentRelationshipId": str(relationship.id),
                "onboardingCaseId": str(onboarding_case.id),
                "clauses": ["岗位聘用", "学校规章"],
            },
            source_business_type="HR05_ONBOARDING",
            source_business_id=str(onboarding_case.id),
        )
        contract_version = agreement_service.activate_initial_version(
            agreement_id=agreement.id,
            version_id=signed.id,
            as_of=today,
        )
        agreement.refresh_from_db()
        contract_version.refresh_from_db()
        self.assertEqual(agreement.status, HrContractAgreement.Status.ACTIVE)
        self.assertEqual(contract_version.status, HrContractVersion.Status.EFFECTIVE)
        self.assertEqual(agreement.staff_id, staff.id)
        self.assertEqual(agreement.employment_relationship_id, relationship.id)
        original_hash = contract_version.content_hash
        original_snapshot = contract_version.content_snapshot_json

        # 4) Create the HR06 target through canonical HR02 services, not a direct
        # target-position fixture, then run a real approved transfer.
        target_org = OrganizationChangeService(
            upstream.scope,
            actor="w-a-full-chain",
        ).create_organization(
            stable_code="WA-FULL-TARGET-COLLEGE",
            name="W-A 全链目标学院",
            org_type="COLLEGE",
            dimension="ADMIN",
            parent_id=upstream.school.id,
            validity_from=today,
        )
        target_catalog = PostCatalogService(
            upstream.scope,
            actor="w-a-full-chain",
        ).create_catalog(
            stable_code="WA-FULL-TARGET-TEACHER",
            name="全链教学科研岗",
            category="PROFESSIONAL_TECHNICAL",
            subcategory="TEACHER",
            validity_from=today,
        )
        target_catalog_version = target_catalog.versions.get(status="ACTIVE")
        target_position = upstream.position_service.create_position(
            position_code="WA-FULL-TARGET-POS-001",
            organization_id=target_org.id,
            post_catalog_version_id=target_catalog_version.id,
            max_incumbents=1,
            validity_from=today,
        )

        action = make_action(TENANT, ChangeActionCode.ORG_POSITION_TRANSFER)
        reason = make_reason(TENANT, ChangeActionCode.ORG_POSITION_TRANSFER)
        change_service = ChangeService(TENANT, actor_user_id=1)
        change_case = change_service.create_case(
            staff_master_id=staff,
            action_id=action,
            reason_id=reason,
            requested_effective_at=today,
            proposals=[
                {
                    "domain": "assignment",
                    "field_code": "organization",
                    "old_value_ref": str(upstream.college.id),
                    "proposed_value_ref": str(target_org.id),
                },
                {
                    "domain": "assignment",
                    "field_code": "position",
                    "old_value_ref": str(upstream.hr02_position.id),
                    "proposed_value_ref": str(target_position.id),
                },
                {
                    "domain": "assignment",
                    "field_code": "post_catalog",
                    "old_value_ref": str(upstream.catalog_version.id),
                    "proposed_value_ref": str(target_catalog_version.id),
                },
            ],
            source_org_id=upstream.college,
            target_org_id=target_org,
            source_position_id=upstream.hr02_position,
            target_position_id=target_position,
            source_assignment_id=source_assignment,
        )
        change_case = change_service.submit(change_case.id)
        change_case = change_service.start_approval(change_case.id)
        change_case = change_service.approve_all(change_case.id)
        self.assertEqual(change_case.status, CaseStatus.APPROVED_WAITING_EFFECTIVE)

        target_reservation = PositionGate(TENANT).reserve_for_case(change_case)
        self.assertIsNotNone(target_reservation)
        self.assertEqual(
            target_reservation.status,
            HrPositionReservation.Status.HELD,
        )

        applied = ApplyService(TENANT, actor_user_id=1).apply_case(
            change_case.id,
            effective_at=today,
            request_id="wa-full-transfer-001",
        )
        self.assertEqual(applied.status, CaseStatus.EFFECTIVE)

        # Same-day transfer intentionally cancels the zero-length onboarding
        # assignment [T,T) and creates the new primary at T. It must not create a
        # second Staff or EmploymentRelationship.
        source_assignment.refresh_from_db()
        self.assertEqual(source_assignment.status, "CANCELLED")
        self.assertEqual(source_assignment.effective_to, today)

        current = EffectiveDatedQueryService(TENANT).primary_assignment_as_of(
            staff.id,
            today,
        )
        self.assertIsNotNone(current)
        self.assertNotEqual(current.id, source_assignment.id)
        self.assertEqual(current.employment_relationship_id_id, relationship.id)
        self.assertEqual(current.organization_id_id, target_org.id)
        self.assertEqual(current.position_id_id, target_position.id)
        self.assertEqual(current.post_catalog_id_id, target_catalog_version.id)
        self.assertEqual(current.source_business_type, "HR06_TRANSFER")

        target_reservation.refresh_from_db()
        self.assertEqual(
            target_reservation.status,
            HrPositionReservation.Status.COMMITTED,
        )

        snapshot = HrChangeEffectiveSnapshot.objects.get(change_case_id=change_case)
        self.assertTrue(snapshot.checksum)
        self.assertEqual(snapshot.effective_at, today)
        self.assertEqual(
            snapshot.position_changes_json["target_position"],
            str(target_position.id),
        )

        # 5) HR06 cannot rewrite signed HR07 evidence. It only emits the formal
        # ContractReviewRequired downstream effect for HR07 to process.
        agreement.refresh_from_db()
        contract_version.refresh_from_db()
        self.assertEqual(agreement.status, HrContractAgreement.Status.ACTIVE)
        self.assertEqual(contract_version.status, HrContractVersion.Status.EFFECTIVE)
        self.assertEqual(contract_version.content_hash, original_hash)
        self.assertEqual(contract_version.content_snapshot_json, original_snapshot)
        self.assertEqual(agreement.staff_id, staff.id)
        self.assertEqual(agreement.employment_relationship_id, relationship.id)

        review = HrChangeDownstreamEffect.objects.get(
            change_case_id=change_case,
            target_domain="HR07",
            effect_type="ContractReviewRequired",
        )
        self.assertEqual(review.status, DownstreamEffectStatus.PENDING)

        # Identity continuity seal: exactly one HR03 person/staff/relationship for
        # this W-A tenant throughout hire, contract, and change.
        self.assertEqual(HrPerson.objects.filter(tenant_id=TENANT).count(), 1)
        self.assertEqual(HrStaffMaster.objects.filter(tenant_id=TENANT).count(), 1)
        self.assertEqual(
            HrEmploymentRelationship.objects.filter(
                tenant_id=TENANT,
                staff_id=staff,
            ).count(),
            1,
        )
        self.assertEqual(
            HrStaffAssignment.objects.filter(
                tenant_id=TENANT,
                employment_relationship_id=relationship,
                assignment_type="PRIMARY",
            ).count(),
            2,
        )
