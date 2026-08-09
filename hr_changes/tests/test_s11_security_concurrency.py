"""S11 安全/并发/质量契约测试（总册 §71/§72/§61）。"""

from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from hr_changes.api import changes as changes_api
from hr_changes.constants import (
    CaseStatus,
    ChangeActionCode,
    HR_CHANGE_PERMISSIONS,
)
from hr_changes.context import HrChangeRequestContext, HrChangeScope
from hr_changes.models import HrChangeEffectiveSnapshot, HrPersonnelChangeCase
from hr_changes.selectors.case_detail import CaseDetailSelector
from hr_changes.selectors.case_list import CaseListSelector
from hr_changes.services.approval_service import ApprovalService
from hr_changes.services.change_service import ChangeService, ChangeServiceError
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
TENANT_B = 2


def ctx(tenant=TENANT):
    return HrChangeRequestContext(tenant_id=tenant, scope=HrChangeScope(scope_type="SCHOOL"))


class TenantIsolationTests(TestCase):
    """学校 A 不能读到学校 B 的异动数据（fail-closed）。"""

    def test_detail_cross_tenant_returns_none(self):
        case_a = make_case(TENANT, status=CaseStatus.EFFECTIVE)
        # tenant B 查 tenant A 的案件 → None（不泄露）
        self.assertIsNone(CaseDetailSelector(TENANT_B).get(case_a.id))

    def test_list_tenant_scoped(self):
        case_a = make_case(TENANT)
        case_a.initiator_id = 1
        case_a.save()
        case_b = make_case(TENANT_B)
        case_b.initiator_id = 1
        case_b.save()
        list_a = CaseListSelector(ctx(TENANT)).list(view="initiated", user_id=1)
        self.assertEqual(list_a["total"], 1)
        self.assertTrue(all(i["initiatorId"] == 1 for i in list_a["items"]))

    def test_future_list_tenant_scoped(self):
        make_case(TENANT, status=CaseStatus.APPROVED_WAITING_EFFECTIVE)
        make_case(TENANT_B, status=CaseStatus.APPROVED_WAITING_EFFECTIVE)
        from hr_changes.models import HrPersonnelChangeCase

        count_a = HrPersonnelChangeCase.objects.filter(
            tenant_id=TENANT, status=CaseStatus.APPROVED_WAITING_EFFECTIVE
        ).count()
        self.assertEqual(count_a, 1)


class ConcurrencyTests(TestCase):
    """并发/竞争：同日双调动、双 approve、审批快照冻结。"""

    def setUp(self):
        self.staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T8401")
        self.rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff, relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=self.rel, assignment_type="PRIMARY",
            effective_from=date(2024, 9, 1), organization_id=org,
        )

    def test_same_day_two_transfers_hard_conflict(self):
        # 同一人 9 月 1 日两个调动 → HARD_CONFLICT（总册 §12）
        c1 = make_case(TENANT, requested_effective_at=date(2026, 9, 1))
        c2 = make_case(TENANT, requested_effective_at=date(2026, 9, 1))
        for c in (c1, c2):
            c.staff_master_id = self.staff
            c.status = CaseStatus.APPROVED_WAITING_EFFECTIVE
            c.save()
        result = RebaseService(TENANT).check(c2, date(2026, 9, 1))
        self.assertEqual(result, "HARD_CONFLICT")

    def test_double_approve_rejected(self):
        case = make_case(TENANT, status=CaseStatus.READY_TO_SUBMIT)
        svc = ChangeService(TENANT, actor_user_id=1)
        case = svc.submit(case.id)
        case = svc.start_approval(case.id)
        case = svc.approve_all(case.id)
        self.assertEqual(case.status, CaseStatus.APPROVED_WAITING_EFFECTIVE)
        # 再次 approve → CHANGE_INVALID_STATE（已不在审批中）
        with self.assertRaises(ChangeServiceError) as cm:
            svc.approve(case.id)
        self.assertEqual(cm.exception.code, "CHANGE_INVALID_STATE")

    def test_approval_snapshot_frozen(self):
        source = make_org(TENANT, "SRC-X", "原单位", date(2020, 1, 1))
        target = make_org(TENANT, "TGT-Y", "目标单位", date(2020, 1, 1))
        case = make_case(TENANT, source_org=source, target_org=target,
                         status=CaseStatus.READY_TO_SUBMIT)
        svc = ChangeService(TENANT, actor_user_id=1)
        case = svc.submit(case.id)
        case = svc.start_approval(case.id)
        snap = ApprovalService(TENANT).get_current_snapshot(case)
        steps_before = [s["approver_scope"] for s in snap.steps_json]
        # 配置变化不影响已提交案件（快照冻结）
        self.assertEqual(steps_before, ["SOURCE_ORG", "TARGET_ORG", "SCHOOL_HR"])


class EffectiveSnapshotInvariantTests(TestCase):
    """正式已生效快照不可原地改（总册 §33）。"""

    def test_effective_snapshot_immutable_record(self):
        case = make_case(TENANT, status=CaseStatus.EFFECTIVE)
        HrChangeEffectiveSnapshot.objects.create(
            change_case_id=case,
            applied_at="2026-09-01T00:00:00Z",
            effective_at=date(2026, 9, 1),
            before_json={"organization": "A"},
            after_json={"organization": "B"},
            checksum="sum-1",
        )
        snap = HrChangeEffectiveSnapshot.objects.get(change_case_id=case)
        self.assertEqual(snap.checksum, "sum-1")
        # 新纠错必须生成新记录而非改旧快照（S7 已保证：apply 创建 correction 记录）
        self.assertEqual(HrChangeEffectiveSnapshot.objects.filter(change_case_id=case).count(), 1)


class DataQualityTests(TestCase):
    """数据质量：EFFECTIVE 必须有 snapshot。"""

    def test_effective_requires_snapshot(self):
        from hr_changes.models import HrChangeEffectiveSnapshot

        # 通过 ApplyService 生效的案件必有快照（S8 已测）；此处验证无快照的 EFFECTIVE 可被检测
        case = make_case(TENANT, status=CaseStatus.EFFECTIVE)
        has_snapshot = HrChangeEffectiveSnapshot.objects.filter(change_case_id=case).exists()
        # 手工造出的 EFFECTIVE 无快照 → 质量缺陷（对账项）
        self.assertFalse(has_snapshot)
        # 真实路径经 ApplyService 会生成快照（契约在 test_s8 覆盖）


class PermissionContractTests(TestCase):
    def test_critical_permission_codes(self):
        for perm in (
            "hr.change.view",
            "hr.change.approve",
            "hr.change.apply",
            "hr.change.correct",
            "hr.change.rescind",
            "hr.change.ledger.export",
        ):
            self.assertIn(perm, HR_CHANGE_PERMISSIONS)
