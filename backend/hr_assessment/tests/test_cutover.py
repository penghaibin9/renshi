"""S12 补齐：新 Cycle 只走 HR12 + 旧页面 Compat + Shadow 执行检查。"""

from django.test import TestCase
from hr_assessment.feature_flags import get_flag, set_flag, list_flags, ensure_no_double_authority
from hr_assessment.models import HrAssessmentCutoverEvent
from hr_control_center.models import HrAuthorityCutover


TENANT = 10001


class CutoverGateTest(TestCase):
    def test_new_cycle_only_flag_defaults_false(self):
        self.assertFalse(get_flag("HR12_NEW_CYCLE_ONLY", tenant_id=TENANT))

    def test_direct_feature_flag_mutation_is_rejected(self):
        with self.assertRaises(RuntimeError):
            set_flag("HR12_NEW_CYCLE_ONLY", True, tenant_id=TENANT)

    def test_shadow_execution_is_derived_from_durable_phase(self):
        HrAssessmentCutoverEvent.objects.create(
            tenant_id=TENANT,
            phase="SHADOW_EXECUTION",
            authority_mode=HrAuthorityCutover.Mode.DUAL_READ_COMPARE,
            operator="test",
            reason="test",
        )
        self.assertTrue(get_flag("HR12_SHADOW_EXECUTION", tenant_id=TENANT))

    def test_no_double_authority_on_hr12_activation(self):
        """切换 HR12 Authority 后，不应同时开启 shadow"""
        HrAuthorityCutover.objects.create(
            tenant_id=TENANT,
            domain=HrAuthorityCutover.Domain.ASSESSMENT,
            mode=HrAuthorityCutover.Mode.AUTHORITY_ONLY,
            reason="test",
        )
        self.assertFalse(get_flag("HR12_SHADOW_EXECUTION", tenant_id=TENANT))
        self.assertTrue(ensure_no_double_authority("HR12", tenant_id=TENANT))

    def test_list_all_flags_complete(self):
        flags = list_flags(tenant_id=TENANT)
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
