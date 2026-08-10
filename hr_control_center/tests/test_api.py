"""
hr_control_center/tests/test_api.py

HR01 API 集成测试（总册 33.6）：
- root apiVersion/schemaVersion/requestId；
- tenant fail-closed（无学校上下文 → 403 TENANT_CONTEXT_REQUIRED）；
- 权限（hr.dashboard.view）；
- bootstrap 同屏一致性（6 KPI + 状态合同）；
- active_headcount 真实计算（LEGACY_CURRENT_SNAPSHOT）；
- UNAVAILABLE 不转 0。

注意：数据创建在 setUpTestData（类级一次），避免 HorillaModel.save() 写
modified_by 时依赖线程残留的 request.user。
"""

from django.test import TestCase, override_settings

from base.models import Company, Department, EmployeeType, JobPosition
from employee.models import Employee, EmployeeWorkInformation
from horilla_auth.models import HorillaUser

BOOTSTRAP_URL = "/api/v1/hr/home/bootstrap"


@override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class HrBootstrapApiTests(TestCase):
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
        cls.dept = Department.objects.create(department="计算机学院")
        cls.dept.company_id.add(cls.company)
        cls.position = JobPosition.objects.create(
            job_position="专任教师", department_id=cls.dept
        )
        cls.position.company_id.add(cls.company)
        cls.emp_type = EmployeeType.objects.create(employee_type="专任教师")
        cls.emp_type.company_id.add(cls.company)

        cls.admin = HorillaUser.objects.create_user(
            username="hr_admin",
            email="hr_admin@test.local",
            password="Admin123!",
            is_superuser=True,
            is_staff=True,
        )
        # CompanyMiddleware 要求登录用户必须关联 Employee，否则会被登出
        admin_emp = Employee.objects.create(
            employee_user_id=cls.admin,
            employee_first_name="管理员",
            employee_last_name="测试",
            email=cls.admin.email,
            phone="13800009999",
        )
        # 必须设置 company，否则 middleware 无默认公司会把 session 重置为 "all"
        EmployeeWorkInformation.objects.filter(employee_id=admin_emp).update(
            company_id_id=cls.company.pk,
        )

        # 创建 3 名员工（官方测试模式：不手动 set_selected_company，用 .update 设置 work_info）
        for i in range(3):
            emp = Employee.objects.create(
                employee_first_name=f"教师{i + 1}",
                employee_last_name=f"测试{i + 1}",
                email=f"teacher{i + 1}@test.local",
                phone=f"1380000{i + 1:04d}",
                is_active=True,
            )
            EmployeeWorkInformation.objects.filter(employee_id=emp).update(
                company_id_id=cls.company.pk,
                department_id_id=cls.dept.pk,
                job_position_id_id=cls.position.pk,
                employee_type_id_id=cls.emp_type.pk,
            )

    def setUp(self):
        self.client.force_login(self.admin)

    def _login_school(self):
        """在请求上下文里选中学校。"""
        self.client.session["selected_company"] = str(self.company.id)
        self.client.session.save()

    def test_root_version_contract(self):
        self._login_school()
        resp = self.client.get(BOOTSTRAP_URL)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        self.assertEqual(data["apiVersion"], "1")
        self.assertEqual(data["schemaVersion"], "1.0")
        self.assertTrue(data["requestId"])
        self.assertTrue(data["generatedAt"])

    def test_tenant_fail_closed(self):
        # 未认证访问 → 403（fail-closed，未登录无学校上下文 → TENANT_CONTEXT_REQUIRED）
        self.client.logout()
        resp = self.client.get(BOOTSTRAP_URL)
        self.assertEqual(resp.status_code, 403)
        # 未登录且无学校上下文：tenant 检查优先 → TENANT_CONTEXT_REQUIRED
        self.assertEqual(resp.json()["error"]["code"], "TENANT_CONTEXT_REQUIRED")

    def test_permission_denied_for_regular_user(self):
        self._login_school()
        user = HorillaUser.objects.create_user(
            username="plain_user", password="x", email="u@test.local"
        )
        # CompanyMiddleware 要求登录用户必须关联 Employee
        user_emp = Employee.objects.create(
            employee_user_id=user,
            employee_first_name="普通",
            employee_last_name="用户",
            email=user.email,
            phone="13800008888",
        )
        EmployeeWorkInformation.objects.filter(employee_id=user_emp).update(
            company_id_id=self.company.pk,
        )
        self.client.force_login(user)
        resp = self.client.get(BOOTSTRAP_URL)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "PERMISSION_DENIED")

    def test_bootstrap_returns_six_metrics(self):
        self._login_school()
        resp = self.client.get(BOOTSTRAP_URL)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        metrics = {m["metricKey"]: m for m in data["metrics"]}
        self.assertEqual(len(metrics), 6)
        self.assertIn("active_headcount", metrics)
        self.assertIn("full_time_teacher", metrics)
        self.assertIn("double_teacher_valid", metrics)
        self.assertIn("new_join_ytd", metrics)
        self.assertIn("departure_ytd", metrics)
        self.assertIn("open_risk_count", metrics)

    def test_active_headcount_real_value(self):
        self._login_school()
        resp = self.client.get(BOOTSTRAP_URL)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        headcount = next(m for m in data["metrics"] if m["metricKey"] == "active_headcount")
        self.assertEqual(headcount["status"], "OK")
        # 3 名测试员工 + admin 自身的 Employee = 4
        self.assertEqual(headcount["value"], 4)
        self.assertEqual(headcount["dataBasis"], "LEGACY_CURRENT_SNAPSHOT")
        self.assertEqual(headcount["scope"]["type"], "SCHOOL")
        self.assertEqual(headcount["definitionVersion"], "1.0")

    def test_unavailable_is_not_zero(self):
        self._login_school()
        resp = self.client.get(BOOTSTRAP_URL)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        double_teacher = next(
            m for m in data["metrics"] if m["metricKey"] == "double_teacher_valid"
        )
        self.assertEqual(double_teacher["status"], "UNAVAILABLE")
        self.assertIsNone(double_teacher["value"])
        self.assertNotEqual(double_teacher["value"], 0)

        departure = next(m for m in data["metrics"] if m["metricKey"] == "departure_ytd")
        self.assertEqual(departure["status"], "UNAVAILABLE")

    def test_same_screen_consistency_contract(self):
        self._login_school()
        resp = self.client.get(BOOTSTRAP_URL)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        ctx = data["context"]
        self.assertEqual(ctx["tenantId"], self.company.id)
        self.assertEqual(ctx["timezone"], "Asia/Shanghai")
        self.assertTrue(ctx["scopeFingerprint"])
        self.assertTrue(ctx["requestSnapshotAt"])
        self.assertEqual(ctx["authorityMode"], "LEGACY_ONLY")
        # 所有 metric 共享同一 asOf
        as_ofs = {m["asOf"] for m in data["metrics"]}
        self.assertEqual(len(as_ofs), 1)
        self.assertEqual(as_ofs.pop(), ctx["asOf"])

    def test_drilldown_contract_present(self):
        self._login_school()
        resp = self.client.get(BOOTSTRAP_URL)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        headcount = next(m for m in data["metrics"] if m["metricKey"] == "active_headcount")
        self.assertEqual(headcount["drilldown"]["contractVersion"], "1")
        self.assertTrue(headcount["drilldown"]["route"])

    def test_metrics_endpoint(self):
        self._login_school()
        resp = self.client.get("/api/v1/hr/home/overview/metrics")
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        keys = {m["metricKey"] for m in data["metrics"]}
        # 核心 6 KPI 全部返回
        for key in (
            "active_headcount",
            "full_time_teacher",
            "double_teacher_valid",
            "new_join_ytd",
            "departure_ytd",
            "open_risk_count",
        ):
            self.assertIn(key, keys)
        # HR08 指标已接入（任务 1）：hr08_active_engagements 必须返回，status 语义正确
        self.assertIn("hr08_active_engagements", keys)
        hr08_metric = next(m for m in data["metrics"] if m["metricKey"] == "hr08_active_engagements")
        self.assertIn(hr08_metric["status"], ("OK", "UNAVAILABLE"))
        # UNAVAILABLE 不转 0：若 status 非 OK 则 value 必须为 None
        if hr08_metric["status"] != "OK":
            self.assertIsNone(hr08_metric["value"])

    def test_cache_control_no_store(self):
        self._login_school()
        resp = self.client.get(BOOTSTRAP_URL)
        self.assertEqual(resp["Cache-Control"], "no-store")
