from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from django.test import RequestFactory, TestCase

from hr_assessment.api.views_assessment import workbench_rows
from hr_assessment.api.views_policy import policy_detail, policy_list
from hr_assessment.models.goal import HrAssessmentGoal, HrAssessmentGoalPlan, HrGoalVersion
from hr_assessment.models.policy import HrAssessmentPolicyPack


class Hr12V2WorkbenchApiTests(TestCase):
    tenant_id = 77

    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            is_superuser=True,
            has_perm=lambda _code: True,
        )

    def _request(self, section: str, tenant_id: int | None = None):
        request = self.factory.get(f"/api/v1/hr/assessments/workbench/{section}")
        request.user = self.user
        request.tenant_id = tenant_id or self.tenant_id
        return request

    def _goal(self, tenant_id: int, code: str, title: str):
        plan = HrAssessmentGoalPlan.objects.create(
            tenant_id=tenant_id,
            name=f"{title}计划",
            status="ACTIVE",
        )
        goal = HrAssessmentGoal.objects.create(
            tenant_id=tenant_id,
            goal_plan=plan,
            goal_code=code,
            status="ACTIVE",
        )
        version = HrGoalVersion.objects.create(
            id=uuid.uuid4(),
            goal=goal,
            version_no=1,
            title=title,
            status="PUBLISHED",
        )
        goal.current_version_id = version.id
        goal.save(update_fields=["current_version_id"])
        return goal

    def test_goal_workbench_is_tenant_scoped_and_hides_internal_ids(self):
        own = self._goal(self.tenant_id, "TEACHING", "本科教学质量提升")
        other = self._goal(88, "RESEARCH", "其它学校科研目标")

        response = workbench_rows(self._request("goals"), "goals")

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)["data"]
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["rows"][0]["name"], "本科教学质量提升")
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(str(own.id), serialized)
        self.assertNotIn(str(other.id), serialized)
        self.assertNotIn("其它学校科研目标", serialized)

    def test_all_authority_workbenches_accept_bounded_empty_reads(self):
        for section in ("term", "ethics", "review", "archive"):
            with self.subTest(section=section):
                response = workbench_rows(self._request(section), section)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(json.loads(response.content)["data"]["rows"], [])

    def test_unknown_workbench_fails_closed(self):
        response = workbench_rows(self._request("unknown"), "unknown")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.content)["error"]["code"], "ASSESSMENT_WORKBENCH_UNKNOWN")

    def test_policy_create_and_rename_are_validated_and_tenant_scoped(self):
        create = self.factory.post(
            "/api/v1/hr/assessments/policies",
            data=json.dumps({
                "code": "annual_2026",
                "name": " 2026 年度考核制度 ",
                "assessment_domain": "annual",
            }),
            content_type="application/json",
        )
        create.user = self.user
        create.tenant_id = self.tenant_id
        response = policy_list(create)
        self.assertEqual(response.status_code, 201)
        pack = HrAssessmentPolicyPack.objects.get(tenant_id=self.tenant_id)
        self.assertEqual(pack.code, "ANNUAL_2026")

        rename = self.factory.put(
            f"/api/v1/hr/assessments/policies/{pack.id}",
            data=json.dumps({"name": " 年度考核制度（修订） "}),
            content_type="application/json",
        )
        rename.user = self.user
        rename.tenant_id = self.tenant_id
        response = policy_detail(rename, pack.id)
        self.assertEqual(response.status_code, 200)
        pack.refresh_from_db()
        self.assertEqual(pack.name, "年度考核制度（修订）")

        wrong_tenant = self.factory.put(
            f"/api/v1/hr/assessments/policies/{pack.id}",
            data=json.dumps({"name": "不应写入"}),
            content_type="application/json",
        )
        wrong_tenant.user = self.user
        wrong_tenant.tenant_id = 88
        self.assertEqual(policy_detail(wrong_tenant, pack.id).status_code, 404)

    def test_policy_write_rejects_invalid_json(self):
        request = self.factory.post(
            "/api/v1/hr/assessments/policies",
            data="{invalid",
            content_type="application/json",
        )
        request.user = self.user
        request.tenant_id = self.tenant_id
        response = policy_list(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["error"]["code"], "INVALID_REQUEST")


class Hr12V2StaticContractTests(TestCase):
    def test_v2_workspace_has_no_placeholder_or_browser_prompt(self):
        project = Path(__file__).resolve().parents[2]
        assessment_js = (project / "static/hr/js/pages/hr12-assessment.js").read_text(encoding="utf-8")
        actions_js = (project / "static/hr/js/pages/hr12-actions.js").read_text(encoding="utf-8")
        template = (project / "hr_assessment/templates/hr_assessment/workspace.html").read_text(encoding="utf-8")

        self.assertNotIn("正在接入", assessment_js)
        self.assertNotIn("window.prompt", actions_js)
        self.assertNotIn("window.alert", assessment_js)
        self.assertNotIn("Policy Pack ${esc(pack.id)}", actions_js)
        self.assertNotIn("人员 ${item.staffId}", assessment_js)
        self.assertIn("hr12-api-workbench", (project / "hr_assessment/api/urls.py").read_text(encoding="utf-8"))
        self.assertIn("{% url 'hr_assessment:hr12-index' %}", template)

    def test_hr12_css_uses_no_gradient(self):
        project = Path(__file__).resolve().parents[2]
        css = "\n".join(
            (project / path).read_text(encoding="utf-8")
            for path in ("static/hr/css/hr12-assessment.css", "static/hr/css/hr12-actions.css")
        ).lower()
        self.assertNotIn("linear-gradient", css)
        self.assertNotIn("radial-gradient", css)
