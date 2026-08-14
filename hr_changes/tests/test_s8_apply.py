"""S8 Apply Service / Outbox / 调度 / Bulk 契约测试。"""

import json
from datetime import date
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
from hr_changes.services.change_service import ChangeService
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