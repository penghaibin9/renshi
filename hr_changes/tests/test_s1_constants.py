"""S1 合同常量测试：枚举 / 错误码 / 权限码 / 事件类型 / 动作-原因种子。"""

from django.test import TestCase

from hr_changes.constants import (
    CASE_ACTIVE_STATUSES,
    CASE_TERMINAL_STATUSES,
    CORRECTION_ACTIONS,
    HR06_ERROR_CODES,
    HR06_EVENT_TYPES,
    HR_CHANGE_PERMISSIONS,
    HR06_PERMISSION_ALIASES,
    SELF_SERVICEABLE_ACTIONS,
    BULK_ONLY_ACTIONS,
    CaseStatus,
    ChangeActionCode,
    ChangeScopeType,
)
from hr_changes.models import HrChangeAction, HrChangeReason


class CaseStatusContractTests(TestCase):
    """总册 §10 状态机：主链 + 终止态分离；RETURNED≠REJECTED。"""

    def test_status_set_partitions(self):
        # 主链与终止态互斥且覆盖全部
        all_statuses = {c for c, _ in CaseStatus.choices}
        self.assertEqual(
            CASE_ACTIVE_STATUSES | CASE_TERMINAL_STATUSES,
            all_statuses,
        )
        self.assertEqual(CASE_ACTIVE_STATUSES & CASE_TERMINAL_STATUSES, set())
        # RETURNED 在主链（可补正重交），REJECTED 在终止态（终局）
        self.assertIn(CaseStatus.RETURNED, CASE_ACTIVE_STATUSES)
        self.assertIn(CaseStatus.REJECTED, CASE_TERMINAL_STATUSES)
        self.assertNotEqual(CaseStatus.RETURNED, CaseStatus.REJECTED)
        # 关键状态存在
        for s in (
            CaseStatus.DRAFT,
            CaseStatus.APPROVED_WAITING_EFFECTIVE,
            CaseStatus.APPLYING,
            CaseStatus.EFFECTIVE,
            CaseStatus.RESCINDED,
            CaseStatus.CORRECTED,
            CaseStatus.APPLY_FAILED,
        ):
            self.assertIn(s, all_statuses)


class ChangeActionContractTests(TestCase):
    """总册 §7 动作冻结 + CHANGE_ACTION_MATRIX。"""

    def test_sixteen_v1_actions_exist(self):
        codes = {c for c, _ in ChangeActionCode.choices}
        expected = {
            "ORG_TRANSFER",
            "POSITION_TRANSFER",
            "ORG_POSITION_TRANSFER",
            "POST_CATEGORY_CHANGE",
            "EMPLOYEE_CATEGORY_CHANGE",
            "EMPLOYMENT_TYPE_CHANGE",
            "MANAGER_CHANGE",
            "LOCATION_CHANGE",
            "ADD_SECONDARY_ASSIGNMENT",
            "END_SECONDARY_ASSIGNMENT",
            "PRIMARY_ASSIGNMENT_SWITCH",
            "TEMPORARY_SECONDMENT",
            "TEMPORARY_ATTACHMENT",
            "RETURN_FROM_TEMPORARY",
            "BULK_ORG_RESTRUCTURE_MOVE",
            "DATA_CORRECTION",
        }
        self.assertEqual(codes, expected)

    def test_action_groupings(self):
        # 数据纠错独立且高权限；批量仅重组管理员
        self.assertIn(ChangeActionCode.DATA_CORRECTION, CORRECTION_ACTIONS)
        self.assertIn(ChangeActionCode.BULK_ORG_RESTRUCTURE_MOVE, BULK_ONLY_ACTIONS)
        self.assertNotIn(ChangeActionCode.EMPLOYMENT_TYPE_CHANGE, SELF_SERVICEABLE_ACTIONS)


class ScopeContractTests(TestCase):
    """总册 §42 Data Scope。"""

    def test_scopes(self):
        scopes = {c for c, _ in ChangeScopeType.choices}
        for s in ("SCHOOL", "COLLEGE", "ORGANIZATION", "SELF", "ASSIGNED_CASES", "SOURCE_ORG", "TARGET_ORG"):
            self.assertIn(s, scopes)


class ErrorCodeContractTests(TestCase):
    """总册 §47 错误码冻结。"""

    def test_key_error_codes(self):
        for code in (
            "CHANGE_INVALID_ACTION",
            "CHANGE_INVALID_STATE",
            "CHANGE_POSITION_CAPACITY_CONFLICT",
            "CHANGE_FUTURE_EVENT_CONFLICT",
            "CHANGE_REBASE_REQUIRED",
            "CHANGE_DEPENDENT_EVENT_EXISTS",
            "CHANGE_TARGET_SCOPE_REQUIRED",
            "CHANGE_APPROVAL_SNAPSHOT_MISMATCH",
            "CHANGE_ALREADY_EFFECTIVE",
            "CHANGE_CORRECTION_REQUIRES_APPROVAL",
            "VERSION_CONFLICT",
        ):
            self.assertIn(code, HR06_ERROR_CODES)


class PermissionContractTests(TestCase):
    """总册 §41 + 00 §28.2：hr.change.* 权限码 + hr06.* alias。"""

    def test_permission_prefix(self):
        for perm in HR_CHANGE_PERMISSIONS:
            self.assertTrue(perm.startswith("hr.change."), perm)
        # alias 不重复授权
        self.assertEqual(len(HR06_PERMISSION_ALIASES), len(set(HR06_PERMISSION_ALIASES.values())))

    def test_critical_permissions(self):
        for perm in (
            "hr.change.view",
            "hr.change.approve",
            "hr.change.apply",
            "hr.change.correct",
            "hr.change.rescind",
            "hr.change.ledger.export",
        ):
            self.assertIn(perm, HR_CHANGE_PERMISSIONS)


class EventTypeContractTests(TestCase):
    """总册 §59 + 00 §28.3：PersonnelChangeEffective 冻结。"""

    def test_key_events(self):
        for evt in (
            "PersonnelChangeApproved",
            "PersonnelChangeEffective",
            "PersonnelChangeCorrected",
            "PersonnelChangeRescinded",
            "TemporaryAssignmentReturnDue",
            "TemporaryAssignmentOverdue",
        ):
            self.assertIn(evt, HR06_EVENT_TYPES)
        # 跨域请求事件
        self.assertIn("CompensationRecalculationRequested", HR06_EVENT_TYPES)
        self.assertIn("ContractReviewRequired", HR06_EVENT_TYPES)


class SeedDataContractTests(TestCase):
    """seed_hr06_defaults 幂等种子（直接用 ORM 建数据路径，不依赖命令执行）。"""

    def test_action_model_unique_per_tenant(self):
        a1 = HrChangeAction.objects.create(tenant_id=1, code="ORG_TRANSFER", name="组织调动")
        HrChangeAction.objects.create(tenant_id=2, code="ORG_TRANSFER", name="组织调动")
        self.assertEqual(HrChangeAction.objects.filter(code="ORG_TRANSFER").count(), 2)
        with self.assertRaises(Exception):
            HrChangeAction.objects.create(tenant_id=1, code="ORG_TRANSFER", name="重复")

    def test_reason_action_code_constraint(self):
        HrChangeAction.objects.create(tenant_id=1, code="ORG_TRANSFER", name="组织调动")
        HrChangeReason.objects.create(
            tenant_id=1, action_code="ORG_TRANSFER", code="WORK_NEED", name="工作需要"
        )
        with self.assertRaises(Exception):
            HrChangeReason.objects.create(
                tenant_id=1, action_code="ORG_TRANSFER", code="WORK_NEED", name="重复"
            )
