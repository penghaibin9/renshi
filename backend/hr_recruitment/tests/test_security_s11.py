"""
hr_recruitment/tests/test_security_s11.py

HR04 S11 安全测试矩阵（《04_HR04_总册》§33）。

覆盖：
- 学校A无法访问学校B招聘/候选（tenant 隔离）；
- public slug / token 不可枚举内部 ID；
- IDOR：跨校 candidate/application 访问 → 404；
- 权限 fail-closed：无 sensitive_view/unlock_score/handoff 权限 → 403；
- candidate self scope：候选人只能看本人申请；
- 高敏 exact-search 权限隔离。

租户隔离用例使用真实 Company 主键作为 tenant_id，并在 MySQL 验收库中执行；
不得以数据库类型或历史夹具问题永久跳过安全门禁。
"""

import json
from datetime import date
from unittest import skipUnless
from uuid import uuid4

from django.apps import apps
from django.contrib.auth.models import Group
from django.test import Client, TestCase, override_settings

LEGACY_SECURITY_AVAILABLE = apps.is_installed("base") and apps.is_installed("employee")
if LEGACY_SECURITY_AVAILABLE:
    from base.models import Company, CompanyGroupAssignment

from hr_recruitment.services.application_service import ApplicationService
from hr_recruitment.services.campaign_service import CampaignService
from hr_recruitment.services.candidate_service import CandidateService

TENANT_A = 10001
TENANT_B = 10002


@override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
@skipUnless(LEGACY_SECURITY_AVAILABLE, "requires installed legacy identity apps")
class TenantIsolationSecurityTests(TestCase):
    """tenant 隔离：A 校数据不可被 B 校看到。"""

    @classmethod
    def setUpTestData(cls):
        # 先建用户，再建公司（Company.created_by FK 在 PG 下严格）
        from horilla_auth.models import HorillaUser
        from employee.models import Employee, EmployeeWorkInformation

        email = f"admin_{uuid4().hex[:6]}@test.local"
        cls.admin_user = HorillaUser.objects.create_user(
            username=f"admin_{uuid4().hex[:6]}",
            email=email,
            password="Admin123!",
            is_superuser=True,
            is_staff=True,
        )
        cls.company_a = Company.objects.create(
            id=TENANT_A,
            company="甲大学", hq=True, address="A", country="CN", state="S", city="C", zip="1",
        )
        cls.company_b = Company.objects.create(
            id=TENANT_B,
            company="乙大学", hq=True, address="B", country="CN", state="S", city="C", zip="1",
        )
        emp = Employee.objects.create(
            employee_user_id=cls.admin_user,
            employee_first_name="管理员",
            employee_last_name="测试",
            email=email,
            phone=f"138{uuid4().hex[:8]}",
        )
        EmployeeWorkInformation.objects.filter(employee_id=emp).update(
            company_id_id=cls.company_a.pk,
        )
        # This account is intentionally authorized for both schools so the
        # assertions below exercise row isolation and IDOR handling rather
        # than the outer tenant-membership gate.
        membership_group = Group.objects.create(name=f"HR04 cross-tenant {uuid4().hex}")
        CompanyGroupAssignment.objects.create(
            user=cls.admin_user,
            company=cls.company_b,
            group=membership_group,
        )

    def setUp(self):
        # A 校招聘项目 + 候选
        self.camp_service_a = CampaignService(tenant_id=TENANT_A, actor="test")
        self.campaign_a = self.camp_service_a.create_campaign(
            code="A-2026-001", title="A 校招聘", campaign_type="SINGLE_POSITION"
        )
        self.position_a = self.camp_service_a.create_position(
            campaign_id=str(self.campaign_a.id),
            post_catalog_name="A 校岗位",
            planned_headcount=1,
        )
        self.cand_service_a = CandidateService(tenant_id=TENANT_A)
        self.candidate_a = self.cand_service_a.create_candidate(
            legal_name="A 校候选人", primary_email="a@test.local"
        )
        app_service_a = ApplicationService(tenant_id=TENANT_A, actor="test")
        draft = app_service_a.save_draft(
            candidate_id=str(self.candidate_a.id),
            recruitment_position_id=str(self.position_a.id),
        )
        self.app_a = app_service_a.submit(application_id=str(draft.id))

    def _login(self, company):
        """复用类级管理员用户登录指定学校。"""
        client = Client()
        client.force_login(self.admin_user)
        session = client.session
        session["selected_company"] = str(company.id)
        session.save()
        return client

    def test_tenant_isolation_candidate_list(self):
        """B 校登录后看不到 A 校候选人。"""
        client_b = self._login(self.company_b)
        resp = client_b.get("/api/v1/hr/recruitment/candidates")
        self.assertEqual(resp.status_code, 200)
        payload = json.loads(resp.content)
        self.assertEqual(payload["data"]["total"], 0)

    def test_tenant_isolation_campaign_list(self):
        client_b = self._login(self.company_b)
        resp = client_b.get("/api/v1/hr/recruitment/campaigns")
        payload = json.loads(resp.content)
        self.assertEqual(payload["data"]["total"], 0)

    def test_idor_candidate_detail(self):
        """B 校访问 A 校候选详情 → 404（不可枚举）。"""
        client_b = self._login(self.company_b)
        resp = client_b.get(f"/api/v1/hr/recruitment/candidates/{self.candidate_a.id}")
        self.assertEqual(resp.status_code, 404)

    def test_idor_application_detail(self):
        client_b = self._login(self.company_b)
        resp = client_b.get(f"/api/v1/hr/recruitment/applications/{self.app_a.id}")
        self.assertEqual(resp.status_code, 404)

    def test_public_token_not_enumerable(self):
        """无效/伪造 token → 404，不能靠枚举拿到内部 ID。"""
        resp = self.client.get("/recruit/ffffffffffffffffffffffffffffffff")
        self.assertEqual(resp.status_code, 404)

    def test_public_position_slug_scoped_to_campaign(self):
        """岗位 slug 必须属于该 campaign。"""
        resp = self.client.get(
            f"/recruit/{self.campaign_a.public_token}/positions/nonexistent-slug"
        )
        self.assertEqual(resp.status_code, 404)

    def test_candidate_self_scope(self):
        """self scope：他人候选看不到 A 候选（需 email+mobile 双因子）。"""
        cand_b = CandidateService(tenant_id=TENANT_B).create_candidate(
            legal_name="B 候选人",
            primary_email="b@test.local",
            primary_mobile="13800005555",
        )
        resp = self.client.post(
            "/recruit/my-applications",
            data=json.dumps(
                {
                    "primary_email": cand_b.primary_email,
                    "primary_mobile": "13800005555",
                    "access_token": self._candidate_receipt(cand_b),
                }
            ),
            content_type="application/json",
        )
        payload = json.loads(resp.content)
        self.assertEqual(payload["data"]["applications"], [])

    @staticmethod
    def _candidate_receipt(candidate):
        from hr_recruitment.public.views import _issue_candidate_receipt

        return _issue_candidate_receipt(candidate)


@override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
@skipUnless(LEGACY_SECURITY_AVAILABLE, "requires installed legacy identity apps")
class PermissionFailClosedTests(TestCase):
    """权限 fail-closed：无权限 → 403（不 200+empty 伪装）。"""

    @classmethod
    def setUpTestData(cls):
        from horilla_auth.models import HorillaUser
        from employee.models import Employee, EmployeeWorkInformation

        email = f"noperm_{uuid4().hex[:6]}@test.local"
        cls.no_perm_user = HorillaUser.objects.create_user(
            username=f"noperm_{uuid4().hex[:6]}",
            email=email,
            password="Admin123!",
        )
        cls.company = Company.objects.create(
            company="丙大学", hq=True, address="C", country="CN", state="S", city="C", zip="1",
        )
        emp = Employee.objects.create(
            employee_user_id=cls.no_perm_user,
            employee_first_name="无权限",
            employee_last_name="用户",
            email=email,
            phone=f"139{uuid4().hex[:8]}",
        )
        EmployeeWorkInformation.objects.filter(employee_id=emp).update(
            company_id_id=cls.company.pk,
        )

    def _login_no_perm(self):
        client = Client()
        client.force_login(self.no_perm_user)
        session = client.session
        session["selected_company"] = str(self.company.id)
        session.save()
        return client

    def test_sensitive_identity_match_requires_perm(self):
        """无 hr04.application.sensitive_view → 403。"""
        client = self._login_no_perm()
        resp = client.post(
            "/api/v1/hr/recruitment/candidates/identity-match-exact",
            data=json.dumps({"national_id": "110101199001011234"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_unlock_score_requires_perm(self):
        client = self._login_no_perm()
        resp = client.post(
            "/api/v1/hr/recruitment/assessment/score-sheets/00000000-0000-0000-0000-000000000001/reopen",
            data=json.dumps({"reason": "x"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_handoff_requires_perm(self):
        client = self._login_no_perm()
        resp = client.post(
            "/api/v1/hr/recruitment/proposed-hires/00000000-0000-0000-0000-000000000001/handoff-to-hr05",
            data=json.dumps({}),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="k",
        )
        self.assertEqual(resp.status_code, 403)

    def test_plan_approve_requires_perm(self):
        client = self._login_no_perm()
        resp = client.post(
            "/api/v1/hr/recruitment/plan-requests/00000000-0000-0000-0000-000000000001/approve",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_tenant_fail_closed(self):
        """未登录 + 无学校上下文 → 403 TENANT_CONTEXT_REQUIRED。"""
        resp = self.client.get("/api/v1/hr/recruitment/campaigns")
        self.assertEqual(resp.status_code, 403)
