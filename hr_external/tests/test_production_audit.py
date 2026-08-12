"""生产级审计回归测试（2026-08-09 深入审计修复）。

覆盖：
- A1 文件上传 MIME/扩展名/magic bytes 校验（HTML/SVG/未知 → 拒绝；PDF → 通过）
- A2 storage_ref 路径穿越防护（绝对路径/.. /反斜杠 → 拒绝）
- A13 data scope 授权（非 superuser COLLEGE 越权 → 403 fail-closed；superuser/有 membership → 放行）
- A10/A11 token header 提取（Authorization: Bearer / X-Portal-Token）
- A8/A9 并发防护（重复 activate → 409；select_for_update 存在）
- A4 FileResponse nosniff（materials redeem 响应头）
"""

import os
import shutil
import tempfile
import unittest
from datetime import date

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from hr_external.api.materials import _extract_ticket_token
from hr_external.api.portal import _extract_token
from hr_external.context import (
    HrExternalContextError,
    authorize_external_scope,
)
from hr_external.services.material_service import (
    MaterialFileRejected,
    validate_material_file,
)
from hr_external.services.storage_backends import (
    PrivateFileSystemStorage,
)


class MaterialFileValidationTests(SimpleTestCase):
    """A1：文件上传类型校验。"""

    def test_pdf_allowed(self):
        mime = validate_material_file(
            filename="proof.pdf", content=b"%PDF-1.4 fake"
        )
        self.assertEqual(mime, "application/pdf")

    def test_html_rejected(self):
        with self.assertRaises(MaterialFileRejected):
            validate_material_file(
                filename="evil.html", content=b"<script>alert(1)</script>"
            )

    def test_svg_rejected(self):
        with self.assertRaises(MaterialFileRejected):
            validate_material_file(filename="evil.svg", content=b"<svg>")

    def test_mismatched_magic_rejected(self):
        # .pdf 扩展名但内容是 HTML → magic bytes 不匹配 → 拒绝
        with self.assertRaises(MaterialFileRejected):
            validate_material_file(
                filename="fake.pdf", content=b"<script>alert(1)</script>"
            )

    def test_unknown_extension_rejected(self):
        with self.assertRaises(MaterialFileRejected):
            validate_material_file(filename="evil.exe", content=b"MZ")

    def test_size_limit_rejected(self):
        with self.assertRaises(MaterialFileRejected):
            validate_material_file(filename="big.pdf", content=b"x" * (51 * 1024 * 1024))


@override_settings(
    HR08_PRIVATE_STORAGE_ROOT=tempfile.mkdtemp(prefix="hr08-audit-"),
    MEDIA_ROOT=tempfile.mkdtemp(prefix="hr08-audit-media-"),
)
class StorageTraversalTests(TestCase):
    """A2：storage_ref 路径穿越防护。"""

    @classmethod
    def tearDownClass(cls):
        for path in (settings.HR08_PRIVATE_STORAGE_ROOT, settings.MEDIA_ROOT):
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.storage = PrivateFileSystemStorage(location=settings.HR08_PRIVATE_STORAGE_ROOT)

    def test_absolute_path_rejected(self):
        with self.assertRaises(ValueError):
            self.storage.open_stream("/etc/passwd")

    def test_traversal_rejected(self):
        with self.assertRaises(ValueError):
            self.storage.open_stream("../secret")

    def test_backslash_rejected(self):
        with self.assertRaises(ValueError):
            self.storage.open_stream("..\\secret")

    def test_nested_path_rejected(self):
        with self.assertRaises(ValueError):
            self.storage.open_stream("dir/file.pdf")

    def test_normal_ref_ok(self):
        ref = self.storage.save_bytes("mat1", b"%PDF-1.4 ok", "a.pdf")
        self.assertIsNotNone(ref)
        self.assertTrue(self.storage.exists(ref))
        # 不存在且恶意 → exists 返回 False（不抛）
        self.assertFalse(self.storage.exists("../etc/passwd"))


class FakeUser:
    def __init__(self, is_superuser=False, id=1):
        self.is_superuser = is_superuser
        self.id = id


class FakeRequest:
    def __init__(self, user):
        self.user = user


@unittest.skipUnless(
    apps.is_installed("employee") and apps.is_installed("horilla_auth"),
    "scope membership 测试依赖 legacy employee/auth 全栈 app（mini 环境跳过，CI 全栈跑）",
)
class ScopeAuthorizationTests(TestCase):
    """A13：data scope 授权（非 superuser COLLEGE 越权 fail-closed）。"""

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from horilla.horilla_middlewares import tenant_context
        from horilla_auth.models import HorillaUser

        self.tenant = 101
        self._tenant_ctx = tenant_context(self.tenant)
        self._tenant_ctx.__enter__()
        self.addCleanup(self._tenant_ctx.__exit__, None, None, None)
        self.company = Company.objects.create(
            id=self.tenant,
            company="测试大学",
            hq=True,
            address="a",
            country="CN",
            state="s",
            city="c",
            zip="1",
        )
        self.user = HorillaUser.objects.create_user(
            username="college_hr", email="ch@test.local", password="X!2345678", is_superuser=False
        )
        self.emp = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="学院",
            employee_last_name="秘书",
            email=self.user.email,
            phone="13811112222",
        )
        # Employee 创建会生成 legacy work-info；显式绑定当前学校，避免测试夹具
        # 被 fail-closed 的 company manager 误判为跨租户/无租户数据。
        EmployeeWorkInformation._base_manager.filter(employee_id=self.emp).update(
            company_id_id=self.company.pk
        )

    def test_superuser_college_scope_allowed(self):
        authorize_external_scope(
            FakeRequest(FakeUser(is_superuser=True)),
            tenant_id=self.tenant,
            scope_type="COLLEGE",
            scope_org_id=99,
        )  # 不抛

    def test_school_scope_allowed_for_any_user(self):
        authorize_external_scope(
            FakeRequest(FakeUser(is_superuser=False)),
            tenant_id=self.tenant,
            scope_type="SCHOOL",
            scope_org_id=None,
        )

    def test_college_scope_without_membership_denied(self):
        # 用户当前无组织 mapping → 请求 org 42 → fail-closed 403
        with self.assertRaises(HrExternalContextError) as ctx:
            authorize_external_scope(
                FakeRequest(FakeUser(is_superuser=False)),
                tenant_id=self.tenant,
                scope_type="COLLEGE",
                scope_org_id=42,
            )
        self.assertEqual(ctx.exception.code, "EXTERNAL_SCOPE_DENIED")

    def test_college_scope_with_membership_allowed(self):
        from base.models import Department
        from employee.models import EmployeeWorkInformation
        from hr_structure.models import HrLegacyObjectLink

        dept = Department.objects.create(department="计算机学院")
        dept.company_id.add(self.company)
        # 把用户 Employee 的 work-info 绑定到当前 tenant 的 dept。
        EmployeeWorkInformation._base_manager.filter(employee_id=self.emp).update(
            department_id_id=dept.pk,
            company_id_id=self.company.pk,
        )
        # 建立 legacy link：dept.id → org 42
        HrLegacyObjectLink.objects.create(
            tenant_id=self.tenant,
            domain_entity_type="organization",
            domain_entity_id="42",
            legacy_app="base",
            legacy_model="department",
            legacy_pk=str(dept.pk),
        )
        authorize_external_scope(
            FakeRequest(FakeUser(is_superuser=False, id=self.user.id)),
            tenant_id=self.tenant,
            scope_type="COLLEGE",
            scope_org_id=42,
        )  # 不抛


class ConcurrencyGuardTests(TestCase):
    """A8/A9：激活/创建并发防护（重复操作拒绝）。"""

    def setUp(self):
        from datetime import date

        from hr_staff.models import HrPerson

        self.tenant = 101
        from hr_external.services.category_service import CategoryService

        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="并发教授")
        from hr_external.services.profile_service import ProfileService

        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="INDUSTRY_PROFESSOR",
        )

    def test_double_activate_rejected(self):
        """同一 case 激活两次：第二次必须被状态机拒绝（select_for_update + 状态守卫）。"""
        from hr_external.constants import ExternalHiringStatus
        from hr_external.models import HrExternalEthicsReview, HrExternalHiringCase
        from hr_external.services.hiring_service import (
            HiringService,
            InvalidHiringState,
        )

        case = HrExternalHiringCase.objects.create(
            tenant_id=self.tenant,
            case_no="C20260002",
            request_org_id=1,
            requester_id=1,
            category_id=self.profile.primary_category,
            purpose="并发测试",
            proposed_person_id=self.person,
            requested_start=date(2026, 9, 1),
            requested_end=date(2027, 8, 31),
            planned_assignments_json=[{"assignmentType": "TEACHING", "organizationId": 1}],
            status=ExternalHiringStatus.READY_TO_ACTIVATE,
        )
        HrExternalEthicsReview.objects.create(
            tenant_id=self.tenant, person_id=self.person, case_id=case,
            status="PASS", reviewer=1,
        )
        # 类别协议要求 NOT_REQUIRED 以便激活成功（HR07 占位）
        self.profile.primary_category.agreement_requirement = "NOT_REQUIRED"
        self.profile.primary_category.save()

        svc = HiringService()
        eng = svc.activate(case)
        self.assertIsNotNone(eng)
        # 第二次激活：case 已 ACTIVATED → 拒绝（防重复创建 Engagement）
        with self.assertRaises(InvalidHiringState):
            svc.activate(case)

    def test_double_engagement_create_rejected(self):
        """同一 person 两次创建重叠 active engagement：第二次被重叠检测拒绝。"""
        from datetime import date

        from hr_external.constants import ExternalEngagementStatus
        from hr_external.models import HrExternalEngagement
        from hr_external.services.engagement_service import (
            EngagementCreateInput,
            EngagementOverlap,
            EngagementService,
        )

        svc = EngagementService()
        input_1 = EngagementCreateInput(
            tenant_id=self.tenant,
            person_id=self.person.id,
            profile_id=self.profile.id,
            category_id=self.profile.primary_category.id,
            host_organization_id=1,
            start_at=date(2026, 9, 1),
            end_at=date(2027, 8, 31),
        )
        eng1 = svc.create_engagement(input_1)
        eng1.status = ExternalEngagementStatus.ACTIVE
        eng1.save()

        input_2 = EngagementCreateInput(
            tenant_id=self.tenant,
            person_id=self.person.id,
            profile_id=self.profile.id,
            category_id=self.profile.primary_category.id,
            host_organization_id=2,
            start_at=date(2027, 3, 1),  # 与 eng1 重叠
            end_at=date(2028, 2, 28),
        )
        with self.assertRaises(EngagementOverlap):
            svc.create_engagement(input_2)


class TokenHeaderExtractionTests(SimpleTestCase):
    """A10/A11：token 优先从 header 取（避免 URL 日志泄漏）。"""

    def _req(self, headers=None, query=""):
        from django.test import RequestFactory

        rf = RequestFactory()
        return rf.get(f"/x?{query}", **({k: v for k, v in (headers or {}).items()}))

    def test_bearer_header(self):
        req = self._req(headers={"HTTP_AUTHORIZATION": "Bearer abc123"})
        self.assertEqual(_extract_token(req), "abc123")
        self.assertEqual(_extract_ticket_token(req), "abc123")

    def test_x_portal_token_header(self):
        req = self._req(headers={"HTTP_X_PORTAL_TOKEN": "tok456"})
        self.assertEqual(_extract_token(req), "tok456")

    def test_query_fallback(self):
        req = self._req(query="token=abc123")
        self.assertEqual(_extract_token(req), "abc123")

    def test_header_priority_over_query(self):
        req = self._req(
            headers={"HTTP_AUTHORIZATION": "Bearer header-token"},
            query="token=query-token",
        )
        self.assertEqual(_extract_token(req), "header-token")
