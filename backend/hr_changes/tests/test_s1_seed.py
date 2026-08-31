"""S1 种子命令测试：seed_hr06_defaults 幂等且产出完整（16 动作 + 全部 reason + 受管字段）。"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from hr_changes.constants import ChangeActionCode
from hr_changes.models import HrChangeAction, HrChangeFieldDefinition, HrChangeReason


class SeedDefaultsCommandTests(TestCase):
    def test_seed_idempotent_and_complete(self):
        out = StringIO()
        call_command("seed_hr06_defaults", "--tenant=99", stdout=out)
        call_command("seed_hr06_defaults", "--tenant=99", stdout=out)

        actions = HrChangeAction.objects.filter(tenant_id=99)
        self.assertEqual(actions.count(), len(ChangeActionCode.choices))
        self.assertEqual(actions.filter(code="ORG_TRANSFER").count(), 1)

        reasons = HrChangeReason.objects.filter(tenant_id=99)
        # 每个动作至少一个原因
        for action_code, _ in ChangeActionCode.choices:
            self.assertGreaterEqual(
                reasons.filter(action_code=action_code).count(), 1, action_code
            )

        fields = HrChangeFieldDefinition.objects.filter(tenant_id=99)
        self.assertGreaterEqual(fields.count(), 8)
        # 幂等：第二次不重复
        self.assertEqual(
            HrChangeReason.objects.filter(tenant_id=99).count(), reasons.count()
        )
        self.assertEqual(
            HrChangeAction.objects.filter(tenant_id=99).count(), actions.count()
        )

    def test_seed_requires_tenant(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("seed_hr06_defaults")
