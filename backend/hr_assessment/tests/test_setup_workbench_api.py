"""HR12 empty-state setup APIs create real versioned authority records."""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from hr_assessment.api.views_assessment import create_annual_case, create_cycle, setup_options
from hr_assessment.api.views_policy import create_policy_version, publish_policy_version
from hr_assessment.models import (
    HrAssessmentCycle,
    HrAssessmentPolicyPack,
    HrAssessmentPolicyVersion,
    HrAssessmentPopulationSnapshot,
    HrExcellentQuotaPolicy,
    HrRatingScaleVersion,
    HrResultRuleVersion,
)
from hr_staff.models import HrPerson, HrStaffMaster


class Hr12SetupWorkbenchApiTests(TestCase):
    tenant_id = 912

    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_superuser(
            username="hr12-setup", email="hr12-setup@example.invalid", password="test-password"
        )
        person = HrPerson.objects.create(tenant_id=self.tenant_id, legal_name="考核测试人员")
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id, person_id=person, staff_no="HR12-001"
        )
        self.pack = HrAssessmentPolicyPack.objects.create(
            tenant_id=self.tenant_id, code="ANNUAL_SETUP", name="年度考核制度", assessment_domain="ANNUAL"
        )

    def request(self, path, body=None, method="POST"):
        if method == "GET":
            request = self.factory.get(path)
        else:
            request = self.factory.post(path, data=json.dumps(body or {}), content_type="application/json")
        request.user = self.user
        request.tenant_id = self.tenant_id
        return request

    def test_policy_cycle_and_case_can_start_from_empty_state(self):
        response = create_policy_version(
            self.request("/versions", {"effectiveFrom": timezone.localdate().isoformat(), "assessmentTypes": ["ANNUAL"]}),
            self.pack.id,
        )
        self.assertEqual(response.status_code, 201)
        version_id = json.loads(response.content)["data"]["id"]
        version = HrAssessmentPolicyVersion.objects.get(id=version_id)
        self.assertEqual(version.status, "DRAFT")
        scale = HrRatingScaleVersion.objects.get(id=version.rating_scale_version_id)
        self.assertEqual(
            [level["code"] for level in scale.levels],
            ["EXCELLENT", "QUALIFIED", "BASIC_QUALIFIED", "UNQUALIFIED"],
        )
        result_rule = HrResultRuleVersion.objects.get(id=version.result_rule_version_id)
        self.assertEqual(
            [band["gradeCode"] for band in result_rule.score_to_grade_mapping["bands"]],
            ["EXCELLENT", "QUALIFIED", "BASIC_QUALIFIED", "UNQUALIFIED"],
        )
        self.assertTrue(
            HrResultRuleVersion.objects.filter(
                tenant_id=self.tenant_id,
                id=version.result_rule_version_id,
                status="PUBLISHED",
            ).exists()
        )
        self.assertTrue(
            HrExcellentQuotaPolicy.objects.filter(
                tenant_id=self.tenant_id,
                id=version.excellent_quota_policy_id,
                status="PUBLISHED",
            ).exists()
        )

        response = publish_policy_version(
            self.request("/publish", {}), self.pack.id, version.id
        )
        self.assertEqual(response.status_code, 200)
        version.refresh_from_db()
        self.assertEqual(version.status, "PUBLISHED")

        now = timezone.now().replace(microsecond=0)
        response = create_cycle(self.request("/cycles", {
            "cycleNo": "ANNUAL-2026", "name": "2026 年度考核", "businessYear": 2026,
            "policyVersionId": str(version.id), "startAt": now.isoformat(),
            "endAt": (now + timedelta(days=30)).isoformat(),
        }))
        self.assertEqual(response.status_code, 201)
        cycle = HrAssessmentCycle.objects.get(id=json.loads(response.content)["data"]["id"])
        self.assertEqual(cycle.lifecycle_status, "PUBLISHED")
        self.assertTrue(hasattr(cycle, "snapshot"))
        self.assertIn("resultRule", cycle.snapshot.frozen_policy_json)
        self.assertIn("excellentQuota", cycle.snapshot.frozen_policy_json)
        self.assertEqual(
            cycle.snapshot.frozen_reviewer_rules_json["scoreAggregation"],
            "AVERAGE",
        )

        response = create_annual_case(self.request("/annual/cases", {
            "cycleId": str(cycle.id), "staffId": str(self.staff.id),
        }))
        self.assertEqual(response.status_code, 201)
        cycle.refresh_from_db()
        self.assertEqual(cycle.lifecycle_status, "ACTIVE")
        self.assertTrue(
            HrAssessmentPopulationSnapshot.objects.filter(
                tenant_id=self.tenant_id,
                cycle=cycle,
                staff_id=self.staff.id,
                included=True,
                excluded=False,
            ).exists()
        )

        response = setup_options(self.request("/setup-options", method="GET"))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)["data"]
        self.assertIn(str(cycle.id), {item["value"] for item in data["cycles"]})
        self.assertIn(str(self.staff.id), {item["value"] for item in data["staff"]})

    def test_term_policy_uses_two_level_result_without_excellent_quota(self):
        pack = HrAssessmentPolicyPack.objects.create(
            tenant_id=self.tenant_id,
            code="TERM_SETUP",
            name="聘期考核制度",
            assessment_domain="TERM",
        )
        response = create_policy_version(
            self.request("/versions", {
                "effectiveFrom": timezone.localdate().isoformat(),
                "assessmentTypes": ["TERM"],
                "qualifiedMinScore": "60",
            }),
            pack.id,
        )
        self.assertEqual(response.status_code, 201)
        version = HrAssessmentPolicyVersion.objects.get(
            id=json.loads(response.content)["data"]["id"]
        )
        self.assertIsNone(version.excellent_quota_policy_id)
        scale = HrRatingScaleVersion.objects.get(id=version.rating_scale_version_id)
        self.assertEqual(
            [level["code"] for level in scale.levels],
            ["QUALIFIED", "UNQUALIFIED"],
        )
        result_rule = HrResultRuleVersion.objects.get(id=version.result_rule_version_id)
        self.assertEqual(
            [band["gradeCode"] for band in result_rule.score_to_grade_mapping["bands"]],
            ["QUALIFIED", "UNQUALIFIED"],
        )
