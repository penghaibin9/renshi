"""
hr_onboarding/tests/test_production_r8.py

HR05 S10 收尾回归测试：
- 任务 DAG 防环检测（自环 / 互环 / 正常无环）；
- 页面路由可访问（5 个新页面 200）；
- Excel 模板下载 / 校验 / 错误工作簿生成。
"""

from datetime import date, timedelta
from uuid import uuid4

from django.test import TestCase

from hr_onboarding.api.exceptions import TaskPrerequisiteNotMetError
from hr_onboarding.models import HrOnboardingTaskDefinition
from hr_onboarding.services.case_service import CaseService
from hr_onboarding.services.task_service import TaskService

from .test_models_s2 import _build_template
from .test_s3 import _handoff_request


class TaskDagCycleTests(TestCase):
    def setUp(self):
        self.tenant_id = 1
        _, self.version, _ = _build_template(tenant_id=self.tenant_id)

    def _add_def(self, code, title, prereqs=None):
        return HrOnboardingTaskDefinition.objects.create(
            tenant_id=self.tenant_id,
            template_version=self.version,
            code=code,
            title=title,
            prerequisite_codes=prereqs or [],
            blocking_level="NON_BLOCKING",
        )

    def test_no_cycle_on_clean_dag(self):
        """正常无环 DAG 不抛错。"""
        a = self._add_def("A", "任务A")
        b = self._add_def("B", "任务B", ["A"])
        c = self._add_def("C", "任务C", ["A", "B"])
        try:
            TaskService(tenant_id=self.tenant_id).validate_no_cycles(self.version.id)
        except TaskPrerequisiteNotMetError:
            self.fail("正常 DAG 不应报环")

    def test_self_cycle_rejected(self):
        """自环 A→A 被检测。"""
        self._add_def("A", "任务A", ["A"])
        with self.assertRaises(TaskPrerequisiteNotMetError):
            TaskService(tenant_id=self.tenant_id).validate_no_cycles(self.version.id)

    def test_mutual_cycle_rejected(self):
        """互环 A→B→A 被检测。"""
        self._add_def("A", "任务A", ["B"])
        self._add_def("B", "任务B", ["A"])
        with self.assertRaises(TaskPrerequisiteNotMetError):
            TaskService(tenant_id=self.tenant_id).validate_no_cycles(self.version.id)

    def test_long_cycle_rejected(self):
        """链式环 A→B→C→A。"""
        self._add_def("A", "任务A", ["C"])
        self._add_def("B", "任务B", ["A"])
        self._add_def("C", "任务C", ["B"])
        with self.assertRaises(TaskPrerequisiteNotMetError):
            TaskService(tenant_id=self.tenant_id).validate_no_cycles(self.version.id)


class PageRoutesTests(TestCase):
    """5 个新页面路由可访问（登录后 200）。"""

    def _get(self, url):
        from django.contrib.auth import get_user_model
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.test import RequestFactory

        User = get_user_model()
        user = User.objects.create_user(username="r8tester", password="x", is_superuser=True)
        request = RequestFactory().get(url)
        # These are direct-view tests, so explicitly run the same session setup
        # that SessionMiddleware provides before Horilla's base/sidebar context
        # processors execute. This keeps the request contract production-real.
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request.user = user
        return request

    def test_prehire_detail_page_accessible(self):
        from hr_onboarding import views

        request = self._get("/hr/onboarding/prehires/dummy-id")
        resp = views.hr05_case_detail(request, case_id=uuid4())
        self.assertEqual(resp.status_code, 200)

    def test_report_checkin_page_accessible(self):
        from hr_onboarding import views

        request = self._get("/hr/onboarding/reporting/dummy-id")
        resp = views.hr05_report_checkin(request, case_id=uuid4())
        self.assertEqual(resp.status_code, 200)

    def test_material_workspace_page_accessible(self):
        from hr_onboarding import views

        request = self._get("/hr/onboarding/materials")
        resp = views.hr05_material_workspace(request)
        self.assertEqual(resp.status_code, 200)

    def test_collaboration_center_page_accessible(self):
        from hr_onboarding import views

        request = self._get("/hr/onboarding/collaboration")
        resp = views.hr05_collaboration_center(request)
        self.assertEqual(resp.status_code, 200)

    def test_probation_detail_page_accessible(self):
        from hr_onboarding import views

        request = self._get("/hr/onboarding/probations/dummy-id")
        resp = views.hr05_probation_detail(request, probation_id=uuid4())
        self.assertEqual(resp.status_code, 200)


class ExcelServiceTests(TestCase):
    def test_template_generation(self):
        from hr_onboarding.services.excel_service import ExcelImportJob

        job = ExcelImportJob(tenant_id=1, uploaded_by=1)
        xlsx = job.template_bytes()
        self.assertIsInstance(xlsx, bytes)
        self.assertGreater(len(xlsx), 0)

    def test_parse_and_validate_valid_data(self):
        import io

        import openpyxl

        from django.core.files.uploadedfile import SimpleUploadedFile

        # 手工构造合法 Excel
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["legal_name", "source_type", "expected_report_date"])
        ws.append(["张三", "HR04_HIRE", "2026-09-01"])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        from hr_onboarding.services.excel_service import ExcelImportJob

        job = ExcelImportJob(tenant_id=1, uploaded_by=1)
        count = job.parse(SimpleUploadedFile("test.xlsx", buf.read(),
                         content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        self.assertEqual(count, 1)
        self.assertTrue(job.validate())

    def test_validation_error_generates_error_workbook(self):
        import io

        import openpyxl

        from django.core.files.uploadedfile import SimpleUploadedFile

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["legal_name", "source_type", "expected_report_date"])
        ws.append(["", "INVALID", "bad-date"])  # 姓名空 + 来源非法 + 日期非法
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        from hr_onboarding.services.excel_service import ExcelImportJob

        job = ExcelImportJob(tenant_id=1, uploaded_by=1)
        job.parse(SimpleUploadedFile("test.xlsx", buf.read(),
                   content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        self.assertFalse(job.validate())
        self.assertEqual(job.status, "VALIDATION_FAILED")
        self.assertGreater(len(job.errors), 0)
        error_xlsx = job.error_workbook()
        self.assertIsInstance(error_xlsx, bytes)
        self.assertGreater(len(error_xlsx), 0)
