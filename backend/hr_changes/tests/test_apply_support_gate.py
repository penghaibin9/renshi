from types import SimpleNamespace

from django.test import SimpleTestCase

from hr_changes.constants import ChangeActionCode, ImpactLevel
from hr_changes.services.impact_service import Hr06ApplySupportProvider


class ApplySupportGateTests(SimpleTestCase):
    def _case(self, action):
        return SimpleNamespace(action_id=SimpleNamespace(code=action))

    def test_post_category_change_is_blocked_until_authority_writer_exists(self):
        items = Hr06ApplySupportProvider().compute(
            self._case(ChangeActionCode.POST_CATEGORY_CHANGE),
            None,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["level"], ImpactLevel.BLOCKER)
        self.assertEqual(items[0]["code"], "CHANGE_INVALID_ACTION")

    def test_location_change_is_not_allowed_to_fake_effective(self):
        items = Hr06ApplySupportProvider().compute(
            self._case(ChangeActionCode.LOCATION_CHANGE),
            None,
        )
        self.assertEqual(items[0]["level"], ImpactLevel.BLOCKER)

    def test_implemented_transfer_action_remains_open(self):
        items = Hr06ApplySupportProvider().compute(
            self._case(ChangeActionCode.ORG_POSITION_TRANSFER),
            None,
        )
        self.assertEqual(items, [])
