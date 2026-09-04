"""HR12 切权必须按学校、按顺序、持久化并禁止缓存直改。"""

from pathlib import Path

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from hr_assessment.feature_flags import set_flag
from hr_assessment.management.commands.cutover import Command


class CutoverDurableContractTests(SimpleTestCase):
    def test_first_phase_cannot_be_skipped(self):
        with self.assertRaises(CommandError):
            Command._assert_order(current_phase="", target_phase="NEW_STAGING")
        Command._assert_order(current_phase="", target_phase="LEGACY_ACTIVE")

    def test_only_next_phase_or_idempotent_replay_is_allowed(self):
        Command._assert_order(
            current_phase="NEW_STAGING",
            target_phase="NEW_STAGING",
        )
        Command._assert_order(
            current_phase="NEW_STAGING",
            target_phase="DUAL_READ_COMPARE",
        )
        with self.assertRaises(CommandError):
            Command._assert_order(
                current_phase="NEW_STAGING",
                target_phase="NEW_AUTHORITY",
            )

    def test_cache_flag_mutation_is_not_a_cutover_boundary(self):
        with self.assertRaises(RuntimeError):
            set_flag("HR12_SHADOW_EXECUTION", True, tenant_id=7)

    def test_command_persists_current_state_and_append_only_event(self):
        command_source = (
            Path(__file__).resolve().parents[1]
            / "management"
            / "commands"
            / "cutover.py"
        ).read_text(encoding="utf-8")
        flags_source = (
            Path(__file__).resolve().parents[1] / "feature_flags.py"
        ).read_text(encoding="utf-8")
        self.assertIn("HrAuthorityCutover.objects.select_for_update", command_source)
        self.assertIn("HrAssessmentCutoverEvent.objects.create", command_source)
        self.assertIn("tenant_id=tenant_id", command_source)
        self.assertIn("set_pms_write_frozen", command_source)
        self.assertNotIn("django.core.cache", flags_source)
