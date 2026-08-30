"""S8 Apply Service / Outbox / 调度 / Bulk 契约测试。"""

import json
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from hr_changes.api import bulk as bulk_api
from hr_changes.constants import CaseStatus, ChangeActionCode, DownstreamEffectStatus
from hr_changes.context import HrChangeRequestContext, HrChangeScope
from hr_changes.integrations.hr02 import PositionGate
from hr_changes.models import (
    HrBulkChangeBatch,
    HrBulkChangeItem,
    HrChangeDownstreamEffect,
    HrChangeEffectiveSnapshot,
    HrChangeOutboxEvent,
    HrPersonnelChangeCase,
)
from hr_changes.services.apply_service import ApplyService, ApplyServiceError
from hr_changes.services.change_service import ChangeService, ChangeServiceError
from hr_changes.services.identity_change_service import IdentityChangeService
from hr_changes.services.rebase_service import RebaseService
from hr_changes.tests.factories import (
    make_action,
    make_case,
    make_org,
    make_person,
    make_position,
    make_reason,
    make_staff,
)
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService

TENANT = 1
FIXTURE_SOURCE = "MIGRATION_VERIFIED"


def ctx():
    return HrChangeRequestContext(tenant_id=TENANT, scope=HrChangeScope(scope_type="SCHOOL"))


class ApplyTransferTests(TestCase):
    """调动全链路：创建→提交→审批→生效→HR03 事实更新 + 快照 + Outbox。"""

    def setUp(self):
        self.staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T8201")
        self.source_org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        self.target_org = make_org(TENANT, "RGXY", "人工智能学院", date(2020, 1, 1))
        self.target_pos = make_position(TENANT, self.target_org, "AI-P300", max_incumbents=1)
        self.rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff, relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=self.rel,
            assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1),
            organization_id=self.source_org,
            source_business_type=FIXTURE_SOURCE,
        )
        self.action = make_action(TENANT, ChangeActionCode.ORG_POSITION_TRANSFER)
        self.reason = make_reason(TENANT, ChangeActionCode.ORG_POSITION_TRANSFER)

    def _approved_case(self, effective_at):
        svc = ChangeService(TENANT, actor_user_id=1)
        case = svc.create_case(
            staff_master_id=self.staff,
            action_id=self.action,
            reason_id=self.reason,
            requested_effective_at=effective_at,
            proposals=[
                {"domain": "assignment", "field_code": "organization",
                 "proposed_value_ref": str(self.target_org.id)},
                {"domain": "assignment", "field_code": "position",
                 "proposed_value_ref": str(self.target_pos.id)},
            ],
            source_org_id=self.source_org,
            target_org_id=self.target_org,
            target_position_id=self.target_pos,
        )
        case = svc.submit(case.id)
        case = svc.start_approval(case.id)
        case = svc.approve_all(case.id)
        PositionGate(TENANT).reserve_for_case(case)
        return case

    def test_apply_transfer_effective(self):
        case = self._approved_case(date.today())
        result = ApplyService(TENANT, actor_user_id=1).apply_case(case.id)
        self.assertEqual(result.status, CaseStatus.EFFECTIVE)

        from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService

        qs = EffectiveDatedQueryService(TENANT)
        primary = qs.primary_assignment_as_of(self.staff.id, date.today())
        self.assertEqual(primary.organization_id_id, self.target_org.id)
        self.assertEqual(primary.position_id_id, self.target_pos.id)

        snap = HrChangeEffectiveSnapshot.objects.get(change_case_id=case)
        self.assertTrue(snap.checksum)
        self.assertEqual(snap.effective_at, date.today())

        outbox = HrChangeOutboxEvent.objects.filter(
            tenant_id=TENANT, event_type="PersonnelChangeEffective"
        )
        self.assertEqual(outbox.count(), 1)
        self.assertEqual(outbox.first().payload_json["caseNo"], case.case_no)

        effects = HrChangeDownstreamEffect.objects.filter(change_case_id=case)
        domains = {e.target_domain for e in effects}
        self.assertIn("HR15", domains)
        self.assertIn("HR11", domains)
        self.assertIn("HR07", domains)

    def test_apply_before_due_rejected(self):
        case = self._approved_case(date.today())
        with self.assertRaises(ApplyServiceError) as cm:
            ApplyService(TENANT).apply_case(case.id, effective_at=date(2030, 1, 1))
        self.assertEqual(cm.exception.code, "CHANGE_EFFECTIVE_DATE_INVALID")

    def test_apply_requires_approved(self):
        case = make_case(TENANT, status=CaseStatus.DRAFT)
        with self.assertRaises(ApplyServiceError) as cm:
            ApplyService(TENANT).apply_case(case.id)
        self.assertEqual(cm.exception.code, "CHANGE_INVALID_STATE")

    def test_apply_failure_on_blocker(self):
        case = self._approved_case(date.today())
        rel = self.rel
        rel.effective_to = date.today() - __import__("datetime").timedelta(days=1)
        rel.status = "ENDED"
        rel.save()
        result = ApplyService(TENANT).apply_case(case.id)
        self.assertEqual(result.status, CaseStatus.APPLY_FAILED)


class ApplyManagerChangeTests(TestCase):
    """直属上级变更只替换 manager，并保留完整 HR03 主岗事实。"""

    def test_manager_change_preserves_primary_assignment_authority(self):
        from hr_staff.models import HrOutboxEvent, HrStaffAuditEvent
        from hr_staff.services.effective_dated_query_service import (
            EffectiveDatedQueryService,
        )

        staff = make_staff(TENANT, make_person(TENANT, "被调整教师"), "T8207")
        old_manager = make_staff(TENANT, make_person(TENANT, "原直属上级"), "T8208")
        new_manager = make_staff(TENANT, make_person(TENANT, "新直属上级"), "T8209")
        org = make_org(TENANT, "JSXY-MGR", "计算机学院", date(2020, 1, 1))
        position = make_position(TENANT, org, "JS-MGR-P01", max_incumbents=2)
        relationship = EmploymentService(TENANT).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        original = AssignmentService(TENANT).create_assignment(
            employment_relationship_id=relationship,
            assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1),
            organization_id=org,
            position_id=position,
            post_catalog_id=position.post_catalog_version_id,
            legacy_department_id=8207,
            legacy_job_position_id=9207,
            assignment_role_code="TEACHING",
            fte=Decimal("0.80"),
            reporting_staff_id=old_manager,
            source_business_type=FIXTURE_SOURCE,
        )

        action = make_action(TENANT, ChangeActionCode.MANAGER_CHANGE)
        reason = make_reason(TENANT, ChangeActionCode.MANAGER_CHANGE)
        service = ChangeService(TENANT, actor_user_id=1)
        case = service.create_case(
            staff_master_id=staff,
            action_id=action,
            reason_id=reason,
            requested_effective_at=date.today(),
            proposals=[
                {
                    "domain": "assignment",
                    "field_code": "reporting_staff",
                    "proposed_value_ref": str(new_manager.id),
                }
            ],
            source_org_id=org,
            source_position_id=position,
        )
        self.assertEqual(case.status, CaseStatus.DRAFT)
        case = service.submit(case.id)
        case = service.start_approval(case.id)
        case = service.approve_all(case.id)
        self.assertEqual(case.status, CaseStatus.APPROVED_WAITING_EFFECTIVE)

        case = ApplyService(TENANT, actor_user_id=1).apply_case(case.id)
        self.assertEqual(case.status, CaseStatus.EFFECTIVE)

        current = EffectiveDatedQueryService(TENANT).primary_assignment_as_of(
            staff.id,
            date.today(),
        )
        self.assertIsNotNone(current)
        self.assertNotEqual(current.id, original.id)
        self.assertEqual(current.organization_id_id, original.organization_id_id)
        self.assertEqual(current.position_id_id, original.position_id_id)
        self.assertEqual(current.post_catalog_id_id, original.post_catalog_id_id)
        self.assertEqual(current.legacy_department_id, original.legacy_department_id)
        self.assertEqual(current.legacy_job_position_id, original.legacy_job_position_id)
        self.assertEqual(current.assignment_role_code, original.assignment_role_code)
        self.assertEqual(current.fte, original.fte)
        self.assertEqual(current.reporting_staff_id_id, new_manager.id)

        original.refresh_from_db()
        self.assertEqual(original.effective_to, date.today())
        staff.refresh_from_db()
        self.assertEqual(staff.primary_assignment_id, current.id)
        self.assertTrue(
            HrStaffAuditEvent.objects.filter(
                tenant_id=TENANT,
                staff_id=staff.id,
                action="PrimaryAssignmentChanged",
                business_type="HR06_TRANSFER",
                business_id=case.case_no,
            ).exists()
        )
        self.assertTrue(
            HrOutboxEvent.objects.filter(
                tenant_id=TENANT,
                event_type="hr.staff.assignment.primary_changed",
                payload_json__assignmentId=str(current.id),
                payload_json__legacyEventType="PrimaryAssignmentChanged",
            ).exists()
        )


class ApplyPrimaryAssignmentSwitchTests(TestCase):
    def test_primary_switch_uses_canonical_refs_and_commits_reservation(self):
        from hr_staff.services.effective_dated_query_service import (
            EffectiveDatedQueryService,
        )

        staff = make_staff(TENANT, make_person(TENANT, "主岗切换教师"), "T8210")
        source_org = make_org(TENANT, "SOURCE-PRIMARY", "原学院", date(2020, 1, 1))
        target_org = make_org(TENANT, "TARGET-PRIMARY", "目标学院", date(2020, 1, 1))
        source_position = make_position(
            TENANT,
            source_org,
            "SOURCE-PRIMARY-P01",
            max_incumbents=1,
        )
        target_position = make_position(
            TENANT,
            target_org,
            "TARGET-PRIMARY-P01",
            max_incumbents=1,
        )
        relationship = EmploymentService(TENANT).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        original = AssignmentService(TENANT).create_assignment(
            employment_relationship_id=relationship,
            assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1),
            organization_id=source_org,
            position_id=source_position,
            post_catalog_id=source_position.post_catalog_version_id,
            source_business_type=FIXTURE_SOURCE,
        )
        action = make_action(TENANT, ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH)
        reason = make_reason(TENANT, ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH)
        case = IdentityChangeService(TENANT, actor_user_id=1).create_identity_change(
            staff_master_id=staff,
            action_id=action,
            reason_id=reason,
            requested_effective_at=date.today(),
            proposals=[
                {
                    "domain": "assignment",
                    "field_code": "organization",
                    "proposed_value_ref": str(target_org.id),
                },
                {
                    "domain": "assignment",
                    "field_code": "position",
                    "proposed_value_ref": str(target_position.id),
                },
            ],
            source_assignment_id=original.id,
        )
        reservation = PositionGate(TENANT).reserve_for_case(case)
        self.assertIsNotNone(reservation)

        service = ChangeService(TENANT, actor_user_id=1)
        case = service.submit(case.id)
        case = service.start_approval(case.id)
        case = service.approve_all(case.id)
        case = ApplyService(TENANT, actor_user_id=1).apply_case(case.id)

        self.assertEqual(case.status, CaseStatus.EFFECTIVE)
        current = EffectiveDatedQueryService(TENANT).primary_assignment_as_of(
            staff.id,
            date.today(),
        )
        self.assertEqual(current.organization_id_id, target_org.id)
        self.assertEqual(current.position_id_id, target_position.id)
        self.assertEqual(
            current.post_catalog_id_id,
            target_position.post_catalog_version_id_id,
        )
        original.refresh_from_db()
        self.assertEqual(original.effective_to, date.today())
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, "COMMITTED")


class ApplyAddSecondaryAssignmentTests(TestCase):
    def test_add_secondary_keeps_primary_and_commits_fte_reservation(self):
        from hr_staff.models import HrStaffAssignment
        from hr_staff.services.effective_dated_query_service import (
            EffectiveDatedQueryService,
        )

        staff = make_staff(TENANT, make_person(TENANT, "增加兼岗教师"), "T8211")
        primary_org = make_org(TENANT, "PRIMARY-ORG", "主岗学院", date(2020, 1, 1))
        secondary_org = make_org(
            TENANT,
            "SECONDARY-ORG",
            "兼岗学院",
            date(2020, 1, 1),
        )
        primary_position = make_position(
            TENANT,
            primary_org,
            "PRIMARY-P01",
            max_incumbents=1,
        )
        secondary_position = make_position(
            TENANT,
            secondary_org,
            "SECONDARY-P01",
            max_incumbents=1,
        )
        relationship = EmploymentService(TENANT).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        primary = AssignmentService(TENANT).create_assignment(
            employment_relationship_id=relationship,
            assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1),
            organization_id=primary_org,
            position_id=primary_position,
            post_catalog_id=primary_position.post_catalog_version_id,
            source_business_type=FIXTURE_SOURCE,
        )
        action = make_action(TENANT, ChangeActionCode.ADD_SECONDARY_ASSIGNMENT)
        reason = make_reason(TENANT, ChangeActionCode.ADD_SECONDARY_ASSIGNMENT)
        case = IdentityChangeService(TENANT, actor_user_id=1).create_identity_change(
            staff_master_id=staff,
            action_id=action,
            reason_id=reason,
            requested_effective_at=date.today(),
            proposals=[
                {
                    "domain": "assignment",
                    "field_code": "organization",
                    "proposed_value_ref": str(secondary_org.id),
                },
                {
                    "domain": "assignment",
                    "field_code": "position",
                    "proposed_value_ref": str(secondary_position.id),
                },
                {
                    "domain": "assignment",
                    "field_code": "fte",
                    "proposed_value_ref": "0.30",
                },
            ],
        )
        reservation = PositionGate(TENANT).reserve_for_case(case)
        self.assertEqual(reservation.reserved_fte, Decimal("0.30"))

        service = ChangeService(TENANT, actor_user_id=1)
        case = service.submit(case.id)
        case = service.start_approval(case.id)
        case = service.approve_all(case.id)
        case = ApplyService(TENANT, actor_user_id=1).apply_case(case.id)

        self.assertEqual(case.status, CaseStatus.EFFECTIVE)
        current_primary = EffectiveDatedQueryService(
            TENANT
        ).primary_assignment_as_of(staff.id, date.today())
        self.assertEqual(current_primary.id, primary.id)
        concurrent = HrStaffAssignment.objects.get(
            tenant_id=TENANT,
            employment_relationship_id=relationship,
            assignment_type="CONCURRENT",
        )
        self.assertEqual(concurrent.organization_id_id, secondary_org.id)
        self.assertEqual(concurrent.position_id_id, secondary_position.id)
        self.assertEqual(
            concurrent.post_catalog_id_id,
            secondary_position.post_catalog_version_id_id,
        )
        self.assertEqual(concurrent.fte, Decimal("0.30"))
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, "COMMITTED")


class ApplyEndSecondaryAssignmentTests(TestCase):
    def test_end_secondary_closes_only_selected_concurrent_assignment(self):
        from hr_staff.models import HrStaffAssignment

        staff = make_staff(TENANT, make_person(TENANT, "取消兼岗教师"), "T8212")
        org = make_org(TENANT, "END-SECONDARY", "兼岗学院", date(2020, 1, 1))
        primary_position = make_position(TENANT, org, "END-PRIMARY", max_incumbents=1)
        first_position = make_position(TENANT, org, "END-CONCURRENT-1", max_incumbents=1)
        second_position = make_position(TENANT, org, "END-CONCURRENT-2", max_incumbents=1)
        relationship = EmploymentService(TENANT).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        primary = AssignmentService(TENANT).create_assignment(
            employment_relationship_id=relationship,
            assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1),
            organization_id=org,
            position_id=primary_position,
            source_business_type=FIXTURE_SOURCE,
        )
        selected = AssignmentService(TENANT).create_assignment(
            employment_relationship_id=relationship,
            assignment_type="CONCURRENT",
            effective_from=date(2025, 9, 1),
            organization_id=org,
            position_id=first_position,
            fte=Decimal("0.20"),
            source_business_type=FIXTURE_SOURCE,
        )
        untouched = AssignmentService(TENANT).create_assignment(
            employment_relationship_id=relationship,
            assignment_type="CONCURRENT",
            effective_from=date(2025, 9, 1),
            organization_id=org,
            position_id=second_position,
            fte=Decimal("0.10"),
            source_business_type=FIXTURE_SOURCE,
        )
        action = make_action(TENANT, ChangeActionCode.END_SECONDARY_ASSIGNMENT)
        reason = make_reason(TENANT, ChangeActionCode.END_SECONDARY_ASSIGNMENT)
        case = IdentityChangeService(TENANT, actor_user_id=1).create_identity_change(
            staff_master_id=staff,
            action_id=action,
            reason_id=reason,
            requested_effective_at=date.today(),
            proposals=[],
            source_assignment_id=selected.id,
        )
        self.assertEqual(case.source_org_id_id, selected.organization_id_id)
        self.assertEqual(case.source_position_id_id, selected.position_id_id)

        service = ChangeService(TENANT, actor_user_id=1)
        case = service.submit(case.id)
        case = service.start_approval(case.id)
        case = service.approve_all(case.id)
        case = ApplyService(TENANT, actor_user_id=1).apply_case(case.id)

        self.assertEqual(case.status, CaseStatus.EFFECTIVE)
        primary.refresh_from_db()
        selected.refresh_from_db()
        untouched.refresh_from_db()
        self.assertIsNone(primary.effective_to)
        self.assertEqual(selected.effective_to, date.today())
        self.assertEqual(selected.status, "ENDED")
        self.assertIsNone(untouched.effective_to)
        self.assertEqual(untouched.status, "ACTIVE")
        self.assertEqual(
            HrStaffAssignment.objects.filter(
                tenant_id=TENANT,
                employment_relationship_id=relationship,
                assignment_type="PRIMARY",
                effective_to__isnull=True,
            ).count(),
            1,
        )

    def test_end_secondary_rejects_primary_source_assignment(self):
        staff = make_staff(TENANT, make_person(TENANT, "误选主岗教师"), "T8213")
        org = make_org(TENANT, "END-REJECT", "主岗学院", date(2020, 1, 1))
        relationship = EmploymentService(TENANT).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        primary = AssignmentService(TENANT).create_assignment(
            employment_relationship_id=relationship,
            assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1),
            organization_id=org,
            source_business_type=FIXTURE_SOURCE,
        )
        action = make_action(TENANT, ChangeActionCode.END_SECONDARY_ASSIGNMENT)
        reason = make_reason(TENANT, ChangeActionCode.END_SECONDARY_ASSIGNMENT)
        with self.assertRaises(ChangeServiceError) as caught:
            IdentityChangeService(TENANT, actor_user_id=1).create_identity_change(
                staff_master_id=staff,
                action_id=action,
                reason_id=reason,
                requested_effective_at=date.today(),
                proposals=[],
                source_assignment_id=primary.id,
            )
        self.assertEqual(caught.exception.code, "CHANGE_SOURCE_ASSIGNMENT_MISMATCH")


class RebaseServiceTests(TestCase):
    def test_hard_conflict_same_day(self):
        staff = make_staff(TENANT, make_person(TENANT, "李某某"), "T8202")
        case1 = make_case(TENANT, requested_effective_at=date(2026, 9, 1))
        case2 = make_case(TENANT, requested_effective_at=date(2026, 9, 1))
        case1.staff_master_id = staff
        case2.staff_master_id = staff
        case1.status = CaseStatus.APPROVED_WAITING_EFFECTIVE
        case2.status = CaseStatus.APPROVED_WAITING_EFFECTIVE
        case1.save()
        case2.save()
        result = RebaseService(TENANT).check(case2, date(2026, 9, 1))
        self.assertEqual(result, "HARD_CONFLICT")

    def test_no_conflict_different_dates(self):
        staff = make_staff(TENANT, make_person(TENANT, "王某某"), "T8203")
        case1 = make_case(TENANT, requested_effective_at=date(2026, 9, 1))
        case2 = make_case(TENANT, requested_effective_at=date(2026, 10, 1))
        case1.staff_master_id = staff
        case2.staff_master_id = staff
        case1.status = CaseStatus.APPROVED_WAITING_EFFECTIVE
        case2.status = CaseStatus.APPROVED_WAITING_EFFECTIVE
        case1.save()
        case2.save()
        result = RebaseService(TENANT).check(case2, date(2026, 10, 1))
        self.assertEqual(result, "NO_CONFLICT")


class DueDispatchTests(TestCase):
    def test_run_due_applications(self):
        staff = make_staff(TENANT, make_person(TENANT, "赵某某"), "T8204")
        org = make_org(TENANT, "RGXY", "人工智能学院", date(2020, 1, 1))
        pos = make_position(TENANT, org, "AI-P301", max_incumbents=1)
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=staff, relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel, assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1), organization_id=org,
            source_business_type=FIXTURE_SOURCE,
        )
        action = make_action(TENANT, ChangeActionCode.ORG_TRANSFER)
        reason = make_reason(TENANT, ChangeActionCode.ORG_TRANSFER)
        svc = ChangeService(TENANT, actor_user_id=1)
        case = svc.create_case(
            staff_master_id=staff, action_id=action, reason_id=reason,
            requested_effective_at=date.today(),
            proposals=[{"domain": "assignment", "field_code": "organization",
                        "proposed_value_ref": str(org.id)}],
            target_org_id=org,
        )
        case = svc.submit(case.id)
        case = svc.start_approval(case.id)
        case = svc.approve_all(case.id)
        self.assertEqual(case.status, CaseStatus.APPROVED_WAITING_EFFECTIVE)

        from hr_changes.jobs.apply_due_cases import run_due_applications

        result = run_due_applications(tenant_id=TENANT)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["applied"], 1)
        case.refresh_from_db()
        self.assertEqual(case.status, CaseStatus.EFFECTIVE)


class BulkServiceTests(TestCase):
    def test_bulk_prevalidate_and_execute(self):
        from hr_changes.services.bulk_service import BulkService

        org = make_org(TENANT, "RGXY", "人工智能学院", date(2020, 1, 1))
        staff1 = make_staff(TENANT, make_person(TENANT, "甲"), "T8205")
        staff2 = make_staff(TENANT, make_person(TENANT, "乙"), "T8206")
        for s in (staff1, staff2):
            rel = EmploymentService(TENANT).start_relationship(
                staff_id=s, relationship_type="REGULAR_EMPLOYMENT",
                effective_from=date(2024, 9, 1),
            )
            AssignmentService(TENANT).create_assignment(
                employment_relationship_id=rel, assignment_type="PRIMARY",
                effective_from=date(2024, 9, 1), organization_id=org,
                source_business_type=FIXTURE_SOURCE,
            )
        action = make_action(TENANT, ChangeActionCode.ORG_TRANSFER)
        make_reason(TENANT, ChangeActionCode.ORG_TRANSFER)
        batch = HrBulkChangeBatch.objects.create(
            tenant_id=TENANT, batch_no="BULK-1", title="批量调动",
            action_id=action, requested_effective_at=date.today(),
            target_org_id=org,
        )
        for idx, s in enumerate([staff1, staff2]):
            HrBulkChangeItem.objects.create(
                batch_id=batch, tenant_id=TENANT, staff_master_id=s, sequence=idx + 1
            )
        svc = BulkService(TENANT, actor_user_id=1)
        pre = svc.prevalidate(batch)
        self.assertEqual(len(pre["results"]), 2)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "PREVALIDATED")

        result = svc.execute(batch.id)
        self.assertEqual(result["batchStatus"], "COMPLETED")
        cases = HrPersonnelChangeCase.objects.filter(
            tenant_id=TENANT, action_id=action, status=CaseStatus.EFFECTIVE
        )
        self.assertEqual(cases.count(), 2)
