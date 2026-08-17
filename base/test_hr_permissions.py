from django.test import SimpleTestCase

from horilla.hr_permissions import permission_aliases


class HrPermissionAliasTests(SimpleTestCase):
    def test_recruitment_legacy_and_canonical_are_equivalent(self):
        self.assertEqual(
            permission_aliases("hr04.plan.view"),
            frozenset({"hr04.plan.view", "hr.recruitment.plan.view"}),
        )
        self.assertEqual(
            permission_aliases("hr.recruitment.plan.view"),
            frozenset({"hr04.plan.view", "hr.recruitment.plan.view"}),
        )

    def test_onboarding_and_external_aliases_are_supported(self):
        self.assertIn("hr05.case.view", permission_aliases("hr.onboarding.case.view"))
        self.assertIn("hr08.profile.view", permission_aliases("hr.external.profile.view"))

    def test_native_canonical_code_is_stable(self):
        self.assertEqual(
            permission_aliases("hr.time.leave.approve"),
            frozenset({"hr.time.leave.approve", "hr11.leave.approve"}),
        )
