"""S2 模型契约测试：Case/Proposal/Transition/Impact/Snapshot/临时/纠错/撤销/批量。"""

import json
from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from hr_changes.constants import CaseStatus, ChangeActionCode
from hr_changes.models import (
    HrBulkChangeBatch,
    HrBulkChangeItem,
    HrChangeAction,
    HrChangeApprovalSnapshot,
    HrChangeCorrection,
    HrChangeDownstreamEffect,
    HrChangeEffectiveSnapshot,
    HrChangeImpactSnapshot,
    HrChangeProposal,
    HrChangeReason,
    HrChangeRescind,
    HrChangeTransition,
    HrPersonnelChangeCase,
    HrTemporaryAssignmentLink,
)
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1


def make_case(**overrides):
    tenant = overrides.get("tenant_id", TENANT)
    action = HrChangeAction.objects.create(
        tenant_id=tenant, code=ChangeActionCode.ORG_TRANSFER, name="组织调动"
    )
    reason = HrChangeReason.objects.create(
        tenant_id=tenant, action_code=ChangeActionCode.ORG_TRANSFER, code="WORK_NEED", name="工作需要"
    )
    staff = make_staff(tenant, make_person(tenant, "张某某"), f"T0601-{tenant}")
    defaults = dict(
        tenant_id=tenant,
        case_no=overrides.pop("case_no", "HRCHG-2026-000001"),
        staff_master_id=staff,
        action_id=action,
        reason_id=reason,
        requested_effective_at=date(2026, 9, 1),
    )
    defaults.update(overrides)
    return HrPersonnelChangeCase.objects.create(**defaults)


class CaseModelTests(TestCase):
    def test_case_no_tenant_unique(self):
        make_case()
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_case(case_no="HRCHG-2026-000001")

    def test_same_case_no_different_tenant_ok(self):
        make_case()
        case2 = make_case(tenant_id=2, case_no="HRCHG-2026-000001")
        self.assertEqual(case2.tenant_id, 2)

    def test_default_status_draft(self):
        case = make_case()
        self.assertEqual(case.status, CaseStatus.DRAFT)
        self.assertEqual(case.version, 1)


class ProposalModelTests(TestCase):
    def test_proposal_unique_per_case_domain_field(self):
        case = make_case()
        HrChangeProposal.objects.create(
            change_case_id=case, domain="assignment", field_code="organization",
            old_value_display="计算机学院", proposed_value_display="人工智能学院",
            effective_at=date(2026, 9, 1),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            HrChangeProposal.objects.create(
                change_case_id=case, domain="assignment", field_code="organization",
                old_value_display="A", proposed_value_display="B",
                effective_at=date(2026, 9, 1),
            )

    def test_proposal_structure_fields(self):
        case = make_case()
        p = HrChangeProposal.objects.create(
            change_case_id=case, domain="assignment", field_code="position",
            old_value_ref="pos-old", old_value_display="软件工程教师",
            proposed_value_ref="pos-new", proposed_value_display="AI教师",
            effective_at=date(2026, 9, 1),
        )
        self.assertEqual(p.old_value_ref, "pos-old")
        self.assertEqual(p.proposed_value_display, "AI教师")


class TransitionModelTests(TestCase):
    def test_transition_records_chain(self):
        case = make_case()
        HrChangeTransition.objects.create(
            change_case_id=case, tenant_id=TENANT,
            from_status=CaseStatus.DRAFT, to_status=CaseStatus.SUBMITTED, action="submit",
        )
        self.assertEqual(case.transitions.count(), 1)
        self.assertEqual(case.transitions.first().action, "submit")


class ImpactSnapshotTests(TestCase):
    def test_impact_snapshot(self):
        case = make_case()
        snap = HrChangeImpactSnapshot.objects.create(
            change_case_id=case,
            blockers_json=[{"code": "CHANGE_POSITION_CAPACITY_CONFLICT", "message": "目标岗位无额度"}],
            warnings_json=[{"code": "ATTENDANCE_RULE_DIFF", "message": "考勤规则将变化"}],
        )
        self.assertEqual(snap.blockers_json[0]["code"], "CHANGE_POSITION_CAPACITY_CONFLICT")
        self.assertEqual(len(snap.warnings_json), 1)


class ApprovalAndEffectiveSnapshotTests(TestCase):
    def test_effective_snapshot_one_per_case(self):
        case = make_case()
        HrChangeEffectiveSnapshot.objects.create(
            change_case_id=case, applied_at=date(2026, 9, 1).isoformat() + "T00:00:00Z",
            effective_at=date(2026, 9, 1),
            before_json={"organization": "计算机学院"},
            after_json={"organization": "人工智能学院"},
            checksum="abc123",
        )
        self.assertEqual(case.effective_snapshot.checksum, "abc123")

    def test_approval_snapshot_versions(self):
        case = make_case()
        HrChangeApprovalSnapshot.objects.create(
            change_case_id=case, workflow_version=1,
            steps_json=[{"step_no": 1, "approver_role": "SOURCE_ORG"}],
        )
        HrChangeApprovalSnapshot.objects.create(
            change_case_id=case, workflow_version=2,
            steps_json=[{"step_no": 1, "approver_role": "TARGET_ORG"}],
        )
        self.assertEqual(case.approval_snapshots.count(), 2)


class DownstreamEffectTests(TestCase):
    def test_unique_per_case_domain_type(self):
        case = make_case()
        HrChangeDownstreamEffect.objects.create(
            change_case_id=case, tenant_id=TENANT, target_domain="HR03",
            effect_type="PersonnelChangeEffective",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            HrChangeDownstreamEffect.objects.create(
                change_case_id=case, tenant_id=TENANT, target_domain="HR03",
                effect_type="PersonnelChangeEffective",
            )


class TemporaryLinkTests(TestCase):
    def test_temporary_link_fields(self):
        from hr_staff.constants import AssignmentType
        from hr_staff.models import HrEmploymentRelationship, HrStaffAssignment
        from hr_staff.services.employment_service import EmploymentService

        staff = make_staff(TENANT, make_person(TENANT, "李某某"), "T0602")
        org = make_org(TENANT, "JSXY", "计算机学院", date(2024, 1, 1))
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=staff, relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        src = HrStaffAssignment.objects.create(
            tenant_id=TENANT, employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            organization_id=org, effective_from=date(2024, 9, 1),
        )
        temp = HrStaffAssignment.objects.create(
            tenant_id=TENANT, employment_relationship_id=rel,
            assignment_type=AssignmentType.SECONDMENT,
            organization_id=org, effective_from=date(2026, 9, 1),
        )
        case = make_case()
        link = HrTemporaryAssignmentLink.objects.create(
            tenant_id=TENANT, change_case_id=case,
            source_assignment_id=src, temporary_assignment_id=temp,
            start_at=date(2026, 9, 1), expected_return_at=date(2027, 9, 1),
        )
        self.assertEqual(link.status, "ACTIVE")
        self.assertEqual(link.source_assignment_status_policy, "KEEP_ACTIVE")


class CorrectionRescindBulkTests(TestCase):
    def test_correction(self):
        case = make_case()
        c = HrChangeCorrection.objects.create(
            tenant_id=TENANT, change_case_id=case,
            correction_type="DATE",
            requested_values_json={"effective_at": "2026-09-02"},
            reason="系统误录",
        )
        self.assertEqual(c.status, "DRAFT")

    def test_rescind_status(self):
        case = make_case(status=CaseStatus.EFFECTIVE)
        r = HrChangeRescind.objects.create(
            tenant_id=TENANT, change_case_id=case, reason="政策调整",
        )
        self.assertEqual(r.status, "RESCIND_REQUESTED")

    def test_bulk_batch_and_items(self):
        action = HrChangeAction.objects.create(
            tenant_id=TENANT, code=ChangeActionCode.BULK_ORG_RESTRUCTURE_MOVE, name="批量组织调整"
        )
        staff1 = make_staff(TENANT, make_person(TENANT, "王某某"), "T0603")
        staff2 = make_staff(TENANT, make_person(TENANT, "赵某某"), "T0604")
        batch = HrBulkChangeBatch.objects.create(
            tenant_id=TENANT, batch_no="BULK-2026-001", title="学院重组",
            action_id=action, requested_effective_at=date(2026, 10, 1),
        )
        HrBulkChangeItem.objects.create(batch_id=batch, tenant_id=TENANT, staff_master_id=staff1, sequence=1)
        HrBulkChangeItem.objects.create(batch_id=batch, tenant_id=TENANT, staff_master_id=staff2, sequence=2)
        self.assertEqual(batch.items.count(), 2)
        self.assertEqual(batch.strategy, "ITEMIZED_COMMIT")
