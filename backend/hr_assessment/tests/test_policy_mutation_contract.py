"""Concurrency guards for HR12 policy authority."""

import inspect

from django.test import SimpleTestCase

from hr_assessment.api import views_policy
from hr_assessment.service import PolicyPackService


class PolicyMutationContractTests(SimpleTestCase):
    def test_policy_update_locks_tenant_pack(self):
        source = inspect.getsource(views_policy.policy_detail)

        self.assertIn("with transaction.atomic()", source)
        self.assertIn("HrAssessmentPolicyPack.objects.select_for_update()", source)
        self.assertIn("tenant_id=tenant", source)

    def test_version_creation_locks_pack_before_allocating_number(self):
        source = inspect.getsource(views_policy.create_policy_version)

        self.assertIn("HrAssessmentPolicyPack.objects.select_for_update()", source)
        self.assertIn('aggregate(max_no=Max("version_no"))', source)
        self.assertIn("version.full_clean()", source)

    def test_publish_locks_version_and_pack(self):
        source = inspect.getsource(PolicyPackService.publish_policy_version)

        self.assertIn("HrAssessmentPolicyVersion.objects.select_for_update()", source)
        self.assertIn("HrAssessmentPolicyPack.objects.select_for_update()", source)
        self.assertIn('version.status != "DRAFT"', source)
