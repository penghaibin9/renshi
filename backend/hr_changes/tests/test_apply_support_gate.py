from types import SimpleNamespace

from django.test import SimpleTestCase

from hr_changes.constants import ChangeActionCode, ImpactLevel
from hr_changes.services.impact_service import Hr06ApplySupportProvider


class ApplySupportGateTests(SimpleTestCase):
    def _case(self, action):
        return SimpleNamespace(action_id=SimpleNamespace(code=action))

    def test_post_category_change_has_authority_writer(self):
        items = Hr06ApplySupportProvider().compute(
            self._case(ChangeActionCode.POST_CATEGORY_CHANGE),
            None,
        )

        self.assertEqual(items, [])

    def test_location_change_has_authority_writer(self):
        items = Hr06ApplySupportProvider().compute(
            self._case(ChangeActionCode.LOCATION_CHANGE),
            None,
        )
        self.assertEqual(items, [])

    def test_implemented_transfer_action_remains_open(self):
        items = Hr06ApplySupportProvider().compute(
            self._case(ChangeActionCode.ORG_POSITION_TRANSFER),
            None,
        )
        self.assertEqual(items, [])
