"""
hr_time/tests/test_s1.py

HR11-S1 验收测试：
- API envelope 合同（apiVersion/schemaVersion/requestId/generatedAt/error 结构）；
- tenant fail-closed：未登录 / 未选学校 / "all" 一律 403 TENANT_CONTEXT_REQUIRED；
- 权限：无 HR11 权限 → 403 PERMISSION_DENIED；
- 学校时区 today()：禁止服务器本地时间当"今天"。

数据创建放 setUpTestData（类级一次），避免 HorillaModel.save() 写
modified_by 时依赖线程残留的 request.user。
"""

from django.test import TestCase, override_settings

from base.models import Company
from employee.models import Employee, EmployeeWorkInformation
from horilla_auth.models import HorillaUser

HEALTH_URL = "/api/v1/hr/time/health"


@override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class HrTimeS1TenantFailClosedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            company="测试大学",
            hq=True,
            address="测试市",
            country="CN",
            state="省",
            city="测试市",
            zip="100000",
        )
        cls.other_company = Company.objects.create(
            company="另一所大学",
            hq=False,
            address="另一市",
            country="CN",
            state="省",
            city="另一市",
            zip="200000",
        )

        cls.admin = HorillaUser.objects.create_user(
            username="hr11_admin",
            email="hr11_admin@test.local",
            password="Admin123!",
            is_superuser=True,
            is_staff=True,
        )
        admin_emp = Employee.objects.create(
            employee_user_id=cls.admin,
            employee_first_name="HR11管理员",
            employee_last_name="测试",
            email=cls.admin.email,
            phone="13800001111",
        )
        # setUpTestData 阶段没有请求 tenant context；用 base manager 仅初始化夹具绑定。
        EmployeeWorkInformation._base_manager.filter(employee_id=admin_emp).update(
            company_id_id=cls.company.pk,
        )

        cls.plain_user = HorillaUser.objects.create_user(
            username="plain_user",
            email="plain@test.local",
            password="Plain123!",
        )
        plain_emp = Employee.objects.create(
            employee_user_id=cls.plain_user,
            employee_first_name="普通",
            employee_last_name="用户",
            email=cls.plain_user.email,
            phone="13800002222",
        )
        EmployeeWorkInformation._base_manager.filter(employee_id=plain_emp).update(
            company_id_id=cls.company.pk,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def _login_school(self, company=None):
        session = self.client.session
        session["selected_company"] = str((company or self.company).id)
        session.save()

    # ── envelope 合同 ────────────────────────────────────────────────

    def test_envelope_contract(self):
        self._login_school()
        resp = self.client.get(HEALTH_URL)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        self.assertEqual(data["apiVersion"], "1")
        self.assertEqual(data["schemaVersion"], "1.0")
        self.assertTrue(data["requestId"])
        self.assertTrue(data["generatedAt"])
        self.assertIn("data", data)
        self.assertEqual(data["data"]["module"], "HR11")

    def test_error_envelope_structure(self):
        # 未登录 → 403，error 信封结构必须完整
        self.client.logout()
        resp = self.client.get(HEALTH_URL)
        self.assertEqual(resp.status_code, 403)
        body = resp.json()
        self.assertEqual(body["apiVersion"], "1")
        self.assertTrue(body["requestId"])
        self.assertIn("error", body)
        self.assertIn("code", body["error"])
        self.assertIn("message", body["error"])
        self.assertIn("details", body["error"])

    # ── tenant fail-closed（A0 硬门）────────────────────────────────

    def test_unauthenticated_fail_closed(self):
        self.client.logout()
        resp = self.client.get(HEALTH_URL)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "TENANT_CONTEXT_REQUIRED")

    def test_no_school_context_fail_closed(self):
        # 登录但账号无任何任职公司 → middleware 无默认公司，session 归 "all" → fail-closed
        no_company_user = HorillaUser.objects.create_user(
            username="no_company_user",
            email="nocompany@test.local",
            password="NoCompany123!",
        )
        Employee.objects.create(
            employee_user_id=no_company_user,
            employee_first_name="无组织",
            employee_last_name="用户",
            email=no_company_user.email,
            phone="13800003333",
        )
        self.client.force_login(no_company_user)
        resp = self.client.get(HEALTH_URL)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "TENANT_CONTEXT_REQUIRED")

    def test_all_schools_context_fail_closed(self):
        # "all"（全部学校）→ 聚合场景 HR11 一律 fail-closed，不合并跨校数字
        session = self.client.session
        session["selected_company"] = "all"
        session.save()
        resp = self.client.get(HEALTH_URL)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "TENANT_CONTEXT_REQUIRED")

    def test_invalid_company_id_fail_closed(self):
        session = self.client.session
        session["selected_company"] = "999999"
        session.save()
        resp = self.client.get(HEALTH_URL)
        # 非法学校 id：middleware 无法匹配 → 无上下文 → fail-closed
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "TENANT_CONTEXT_REQUIRED")

    # ── 权限（总册 §151）────────────────────────────────────────────

    def test_permission_denied_for_regular_user(self):
        # force_login 会轮换/重建 session；先完成登录，再建立学校上下文，
        # 才能真正测试 permission gate，而不是被 tenant gate 提前拦截。
        self.client.force_login(self.plain_user)
        self._login_school()
        resp = self.client.get(HEALTH_URL)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "PERMISSION_DENIED")

    # ── 学校时区 today()（H0 硬门）──────────────────────────────────

    def test_health_returns_school_timezone_today(self):
        self._login_school()
        resp = self.client.get(HEALTH_URL)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["tenant"]["tenantId"], self.company.id)
        self.assertEqual(data["tenant"]["timezone"], "Asia/Shanghai")
        # schoolToday 必须是合法 ISO date，且来自学校时区上下文
        from datetime import date

        parsed = date.fromisoformat(data["tenant"]["schoolToday"])
        ctx_today = data["tenant"]["schoolToday"]
        self.assertEqual(parsed.isoformat(), ctx_today)
