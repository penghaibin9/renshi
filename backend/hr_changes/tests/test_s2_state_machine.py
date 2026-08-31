"""S2 状态机契约测试：合法/非法转移、RETURNED≠REJECTED、终局态。"""

from django.test import TestCase

from hr_changes.constants import CaseStatus
from hr_changes.services.state_machine import (
    ChangeStateError,
    allowed_next_status,
    can_transition,
    is_terminal,
    transition,
)


class StateMachineTests(TestCase):
    def test_main_chain(self):
        # 主链合法转移
        self.assertTrue(can_transition("validate", CaseStatus.DRAFT, CaseStatus.VALIDATING))
        self.assertTrue(can_transition("ready", CaseStatus.VALIDATING, CaseStatus.READY_TO_SUBMIT))
        self.assertTrue(can_transition("submit", CaseStatus.READY_TO_SUBMIT, CaseStatus.SUBMITTED))
        self.assertTrue(can_transition("enter_approval", CaseStatus.SUBMITTED, CaseStatus.UNDER_APPROVAL))
        self.assertTrue(can_transition("approve", CaseStatus.UNDER_APPROVAL, CaseStatus.APPROVED_WAITING_EFFECTIVE))
        self.assertTrue(can_transition("apply", CaseStatus.APPROVED_WAITING_EFFECTIVE, CaseStatus.APPLYING))
        self.assertTrue(can_transition("apply_success", CaseStatus.APPLYING, CaseStatus.EFFECTIVE))
        self.assertTrue(can_transition("close", CaseStatus.EFFECTIVE, CaseStatus.CLOSED))

    def test_returned_resubmitted_cycle(self):
        # RETURNED 可补正重交（主链），REJECTED 终局
        self.assertTrue(can_transition("return", CaseStatus.UNDER_APPROVAL, CaseStatus.RETURNED))
        self.assertTrue(can_transition("resubmit", CaseStatus.RETURNED, CaseStatus.RESUBMITTED))
        self.assertTrue(can_transition("enter_approval", CaseStatus.RESUBMITTED, CaseStatus.UNDER_APPROVAL))
        self.assertFalse(is_terminal(CaseStatus.RETURNED))
        self.assertTrue(is_terminal(CaseStatus.REJECTED))

    def test_illegal_transition_raises(self):
        with self.assertRaises(ChangeStateError) as cm:
            transition("approve", CaseStatus.DRAFT, CaseStatus.APPROVED_WAITING_EFFECTIVE)
        self.assertEqual(cm.exception.code, "CHANGE_INVALID_STATE")
        # 动作与目标不匹配
        with self.assertRaises(ChangeStateError):
            transition("apply_success", CaseStatus.APPLYING, CaseStatus.CLOSED)

    def test_reject_is_terminal(self):
        self.assertTrue(can_transition("reject", CaseStatus.UNDER_APPROVAL, CaseStatus.REJECTED))
        self.assertTrue(is_terminal(CaseStatus.REJECTED))
        # REJECTED 不能 return
        self.assertNotIn(
            CaseStatus.RETURNED, allowed_next_status("return", CaseStatus.REJECTED)
        )

    def test_withdraw_cancel_apply_failed_rescinded_corrected(self):
        self.assertTrue(is_terminal(CaseStatus.WITHDRAWN))
        self.assertTrue(is_terminal(CaseStatus.CANCELLED))
        self.assertTrue(is_terminal(CaseStatus.APPLY_FAILED))
        self.assertTrue(is_terminal(CaseStatus.RESCINDED))
        self.assertTrue(is_terminal(CaseStatus.CORRECTED))
        # 撤销只能对已生效
        self.assertTrue(can_transition("rescind", CaseStatus.EFFECTIVE, CaseStatus.RESCINDED))
        self.assertFalse(can_transition("rescind", CaseStatus.DRAFT, CaseStatus.RESCINDED))

    def test_transition_returns_target(self):
        self.assertEqual(
            transition("submit", CaseStatus.READY_TO_SUBMIT, CaseStatus.SUBMITTED),
            CaseStatus.SUBMITTED,
        )
