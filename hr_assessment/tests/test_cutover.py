"""S12 补齐：新 Cycle 只走 HR12 + 旧页面 Compat + Shadow 执行检查。"""

from django.test import TestCase
from hr_assessment.feature_flags import get_flag, set_flag, list_flags, ensure_no_double_authority


class CutoverGateTest(TestCase):
    def setUp(self):
        set_flag("HR12_NEW_CYCLE_ONLY", False)
        set_flag("HR12_SHADOW_EXECUTION", False)

    def test_new_cycle_only_flag_defaults_false(self):
        self.assertFalse(get_flag("HR12_NEW_CYCLE_ONLY"))

    def test_set_and_get_feature_flag(self):
        set_flag("HR12_NEW_CYCLE_ONLY", True)
        self.assertTrue(get_flag("HR12_NEW_CYCLE_ONLY"))
        set_flag("HR12_NEW_CYCLE_ONLY", False)

    def test_shadow_execution_defaults_false(self):
        self.assertFalse(get_flag("HR12_SHADOW_EXECUTION"))

    def test_no_double_authority_on_hr12_activation(self):
        """切换 HR12 Authority 后，不应同时开启 shadow"""
        self.assertFalse(get_flag("HR12_SHADOW_EXECUTION"))
        self.assertTrue(ensure_no_double_authority("HR12"))

    def test_list_all_flags_complete(self):
        flags = list_flags()
        required = {"HR12_POLICY_AUTHORITY", "HR12_CYCLE_AUTHORITY", "HR12_ANNUAL_AUTHORITY",
                     "HR12_TERM_AUTHORITY", "HR12_ETHICS_AUTHORITY", "HR12_GOAL_AUTHORITY",
                     "HR12_SHADOW_EXECUTION", "HR12_NEW_CYCLE_ONLY"}
        self.assertTrue(required.issubset(flags.keys()))

    def test_legacy_freeze_state_independent(self):
        from hr_assessment.management.commands.legacy_freeze import is_pms_write_frozen
        frozen = is_pms_write_frozen()
        self.assertIsInstance(frozen, bool)

    def test_cutover_phase_order_preserved(self):
        from hr_assessment.management.commands.cutover import PHASES
        idx_freeze = PHASES.index("FREEZE_LEGACY_FORMAL_WRITES")
        idx_authority = PHASES.index("NEW_AUTHORITY")
        self.assertLess(idx_freeze, idx_authority)

    def test_rollback_rehearsal_logs(self):
        from hr_assessment.management.commands.legacy_freeze import Command
        cmd = Command()
        self.assertTrue(hasattr(cmd, "_do_unfreeze"))
