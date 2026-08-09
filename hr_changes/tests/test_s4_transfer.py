"""S4 校内调动契约测试：create_transfer / validate_transfer / PositionGate / Before-After / API。"""

import json
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from hr_changes.api import transfers as transfers_api
from hr_changes.constants import CaseStatus, ChangeActionCode
from hr_changes.context import HrChangeRequestContext, HrChangeScope
from hr_changes.integrations.hr02 import PositionGate
from hr_changes.models import HrPersonnelChangeCase
from hr_changes.services.change_service import ChangeServiceError
from hr_changes.services.transfer_service import TransferService
from hr_changes.tests.factories import (
    make_action,
    make_org,
    make_person,
    make_position,
    make_reason,
    make_staff,
)
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService

TENANT = 1


def ctx():
    return HrChangeRequestContext(tenant_id=TENANT, scope=HrChangeScope(scope_type="SCHOOL"))


class TransferServiceTests(TestCase):
    def setUp(self):
        self.action = make_action(TENANT, ChangeActionCode.ORG_POSITION_TRANSFER)
        self.reason = make_reason(TENANT, ChangeActionCode.ORG_POSITION_TRANSFER)
        self.staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T9001")
        self.source_org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        self.target_org = make_org(TENANT, "RGXY", "人工智能学院", date(2020, 1, 1))
        self.target_pos = make_position(TENANT, self.target_org, "AI-P088", max_incumbents=1)
        self.rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff, relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=self.rel,
            assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1),
            organization_id=self.source_org,
        )

    def test_create_org_position_transfer(self):
        case = TransferService(TENANT, actor_user_id=1).create_transfer(
            staff_master_id=self.staff,
            action_id=self.action,
            reason_id=self.reason,
            requested_effective_at=date(2026, 9, 1),
            source_org_id=self.source_org,
            target_org_id=self.target_org,
            target_position_id=self.target_pos,
        )
        self.assertEqual(case.status, CaseStatus.DRAFT)
        codes = {p.field_code for p in case.proposals.all()}
        self.assertIn("organization", codes)
        self.assertIn("position", codes)

    def test_non_transfer_action_rejected(self):
        manager_action = make_action(TENANT, ChangeActionCode.MANAGER_CHANGE)
        with self.assertRaises(ChangeServiceError) as cm:
            TransferService(TENANT).create_transfer(
                staff_master_id=self.staff,
                action_id=manager_action,
                reason_id=self.reason,
                requested_effective_at=date(2026, 9, 1),
                target_org_id=self.target_org,
            )
        self.assertEqual(cm.exception.code, "CHANGE_INVALID_ACTION")

    def test_org_transfer_requires_target_org(self):
        org_action = make_action(TENANT, ChangeActionCode.ORG_TRANSFER)
        org_reason = make_reason(TENANT, ChangeActionCode.ORG_TRANSFER)
        with self.assertRaises(ChangeServiceError) as cm:
            TransferService(TENANT).create_transfer(
                staff_master_id=self.staff,
                action_id=org_action,
                reason_id=org_reason,
                requested_effective_at=date(2026, 9, 1),
            )
        self.assertEqual(cm.exception.code, "CHANGE_TARGET_ORG_INVALID")

    def test_validate_transfer_capacity_blocker(self):
        # 占用目标岗位后再发起调动 → 容量 blocker
        self.target_pos.max_incumbents = 1
        self.target_pos.save()
        other = make_staff(TENANT, make_person(TENANT, "李某某"), "T9002")
        other_org = make_org(TENANT, "WX", "信息中心", date(2020, 1, 1))
        rel2 = EmploymentService(TENANT).start_relationship(
            staff_id=other, relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel2,
            assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1),
            organization_id=self.target_org,
            position_id=self.target_pos,
        )
        case = TransferService(TENANT, actor_user_id=1).create_transfer(
            staff_master_id=self.staff,
            action_id=self.action,
            reason_id=self.reason,
            requested_effective_at=date(2026, 9, 1),
            source_org_id=self.source_org,
            target_org_id=self.target_org,
            target_position_id=self.target_pos,
        )
        result = TransferService(TENANT).validate_transfer(case)
        codes = {b["code"] for b in result["blockers"]}
        self.assertIn("CHANGE_POSITION_CAPACITY_CONFLICT", codes)

    def test_before_after(self):
        case = TransferService(TENANT, actor_user_id=1).create_transfer(
            staff_master_id=self.staff,
            action_id=self.action,
            reason_id=self.reason,
            requested_effective_at=date(2026, 9, 1),
            source_org_id=self.source_org,
            target_org_id=self.target_org,
            target_position_id=self.target_pos,
        )
        ba = TransferService(TENANT).current_vs_target(case)
        self.assertEqual(ba["before"]["organization"], "计算机学院")
        self.assertEqual(ba["after"]["organization"], "人工智能学院")
        self.assertEqual(ba["after"]["position"], "AI-P088")


class PositionGateTests(TestCase):
    def test_reserve_commit_release(self):
        org = make_org(TENANT, "RGXY", "人工智能学院", date(2020, 1, 1))
        pos = make_position(TENANT, org, "AI-P100", max_incumbents=1)
        case = HrPersonnelChangeCase(
            tenant_id=TENANT, case_no="HRCHG-2026-999901",
            staff_master_id=make_staff(TENANT, make_person(TENANT, "王某某"), "T9003"),
            action_id=make_action(TENANT, ChangeActionCode.POSITION_TRANSFER),
            reason_id=make_reason(TENANT, ChangeActionCode.POSITION_TRANSFER),
            requested_effective_at=date(2026, 9, 1),
            target_position_id=pos,
        )
        case.save()
        gate = PositionGate(TENANT)
        r1 = gate.reserve_for_case(case)
        self.assertEqual(r1.status, "HELD")
        # 幂等：同一 case 重复 reserve 返回同一预占
        r2 = gate.reserve_for_case(case)
        self.assertEqual(r1.id, r2.id)
        # 容量已被预占占满
        blockers = gate.check_capacity(case)
        self.assertTrue(any(b["code"] == "CHANGE_POSITION_CAPACITY_CONFLICT" for b in blockers))
        # 提交
        gate.commit_for_case(case)
        self.assertEqual(
            HrPositionReservationRow(case).status, "COMMITTED"
        )

    def test_capacity_free(self):
        org = make_org(TENANT, "RGXY", "人工智能学院", date(2020, 1, 1))
        pos = make_position(TENANT, org, "AI-P101", max_incumbents=1)
        case = HrPersonnelChangeCase(
            tenant_id=TENANT, case_no="HRCHG-2026-999902",
            staff_master_id=make_staff(TENANT, make_person(TENANT, "赵某某"), "T9004"),
            action_id=make_action(TENANT, ChangeActionCode.POSITION_TRANSFER),
            reason_id=make_reason(TENANT, ChangeActionCode.POSITION_TRANSFER),
            requested_effective_at=date(2026, 9, 1),
            target_position_id=pos,
        )
        case.save()
        self.assertEqual(PositionGate(TENANT).check_capacity(case), [])


class HrPositionReservationRow:
    def __init__(self, case):
        from hr_structure.models import HrPositionReservation

        self.row = (
            HrPositionReservation.objects.filter(
                tenant_id=TENANT, source_business_id=str(case.id)
            )
            .first()
        )

    @property
    def status(self):
        return self.row.status if self.row else None


class TransferApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_user(
            username="hr06xfer", password="x", is_superuser=True
        )
        self.action = make_action(TENANT, ChangeActionCode.ORG_POSITION_TRANSFER)
        self.reason = make_reason(TENANT, ChangeActionCode.ORG_POSITION_TRANSFER)
        self.staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T9101")
        self.source_org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        self.target_org = make_org(TENANT, "RGXY", "人工智能学院", date(2020, 1, 1))
        self.target_pos = make_position(TENANT, self.target_org, "AI-P200", max_incumbents=1)
        self.rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff, relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=self.rel,
            assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1),
            organization_id=self.source_org,
        )

    def _req(self, method, path, body=None):
        if body is not None:
            request = getattr(self.factory, method)(path, data=json.dumps(body), content_type="application/json")
        else:
            request = getattr(self.factory, method)(path)
        request.user = self.user
        return request

    def test_create_transfer_api(self):
        body = {
            "staffMasterId": str(self.staff.id),
            "actionId": str(self.action.id),
            "reasonId": str(self.reason.id),
            "requestedEffectiveAt": "2026-09-01",
            "sourceOrgId": self.source_org.id,
            "targetOrgId": self.target_org.id,
            "targetPositionId": self.target_pos.id,
        }
        with mock.patch("hr_changes.api.transfers.make_hr_change_context", return_value=ctx()):
            resp = transfers_api.transfer_create(self._req("post", "/api/hr/v1/changes/transfers", body))
        self.assertEqual(resp.status_code, 201)
        data = json.loads(resp.content)["data"]
        self.assertEqual(data["actionLabel"], "组织+岗位调动")
        self.assertIn("beforeAfter", data)
        self.assertEqual(data["beforeAfter"]["after"]["position"], "AI-P200")

    def test_transfer_list_api(self):
        from hr_changes.tests.factories import make_case

        make_case(TENANT, ChangeActionCode.ORG_POSITION_TRANSFER,
                  target_org=self.target_org, status=CaseStatus.EFFECTIVE)
        with mock.patch("hr_changes.api.transfers.make_hr_change_context", return_value=ctx()):
            resp = transfers_api.transfer_list(self._req("get", "/api/hr/v1/changes/transfers"))
        body = json.loads(resp.content)
        self.assertEqual(body["data"]["total"], 1)
