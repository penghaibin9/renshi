"""S3 · 外聘教师库契约测试。

覆盖（总册 §24-26/§82/§110/§120）：
- ProfileService 编号/创建/重复阻断；
- Selector 列表：WHERE→COUNT→ORDER→PAGE；筛选/分页；scope 裁剪（COLLEGE）；
- IdentityMatch：EXACT（证件指纹）/ POSSIBLE（姓名+来源单位组合）/ NO_MATCH / INSUFFICIENT_DATA；
- ImportService：CSV staging/校验/confirm/execute（分批事务真实执行；XLSX 解析 # [总控占位]）。
"""

import csv
import io
from datetime import date

from django.test import TestCase

from hr_external.constants import ExternalEngagementStatus, IdentityMatchLevel
from hr_external.models import (
    HrExternalImportJob,
    HrExternalImportRow,
    HrExternalTeacherProfile,
)
from hr_external.selectors import list_external_profiles
from hr_external.selectors.profile_selector import ProfileFilterSpec
from hr_external.services.category_service import CategoryService
from hr_external.services.engagement_service import EngagementService, EngagementCreateInput
from hr_external.services.identity_match_service import IdentityMatchService
from hr_external.services.import_service import ImportService, ImportValidationError
from hr_external.services.profile_service import ProfileService


class ProfileServiceTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person_a = HrPerson.objects.create(tenant_id=self.tenant, legal_name="张三")
        self.service = ProfileService()

    def test_create_profile_with_category(self):
        p = self.service.create_profile(
            tenant_id=self.tenant,
            person_id=self.person_a.id,
            primary_category_code="INDUSTRY_PROFESSOR",
            source_organization_name="XX集团",
        )
        self.assertEqual(p.primary_category.code, "INDUSTRY_PROFESSOR")
        self.assertTrue(p.external_teacher_no.startswith("EXT"))

    def test_duplicate_profile_blocked(self):
        self.service.create_profile(tenant_id=self.tenant, person_id=self.person_a.id)
        from hr_external.services.profile_service import DuplicateProfile

        with self.assertRaises(DuplicateProfile):
            self.service.create_profile(tenant_id=self.tenant, person_id=self.person_a.id)


class ProfileSelectorTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.service = ProfileService()
        self.p1 = HrPerson.objects.create(tenant_id=self.tenant, legal_name="张三")
        self.p2 = HrPerson.objects.create(tenant_id=self.tenant, legal_name="李四")
        self.profile_a = self.service.create_profile(
            tenant_id=self.tenant,
            person_id=self.p1.id,
            primary_category_code="INDUSTRY_PROFESSOR",
            source_organization_name="XX集团",
            industry_domain="智能制造",
            highest_professional_title="高级工程师",
        )
        self.service.create_profile(
            tenant_id=self.tenant,
            person_id=self.p2.id,
            primary_category_code="PART_TIME_TEACHER",
            source_organization_name="YY大学",
            industry_domain="计算机",
        )

    def test_list_where_count_order_page(self):
        spec = ProfileFilterSpec(tenant_id=self.tenant, page=1, page_size=10)
        total, items = list_external_profiles(spec)
        self.assertEqual(total, 2)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["legalName"], "李四")  # 默认 -updated_at 最新在前

    def test_filter_by_keyword_and_category(self):
        spec = ProfileFilterSpec(tenant_id=self.tenant, keyword="张三")
        total, _ = list_external_profiles(spec)
        self.assertEqual(total, 1)

        spec = ProfileFilterSpec(tenant_id=self.tenant, category_code="PART_TIME_TEACHER")
        total, items = list_external_profiles(spec)
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["legalName"], "李四")

    def test_filter_by_industry_and_title(self):
        spec = ProfileFilterSpec(tenant_id=self.tenant, industry_domain="智能制造")
        total, _ = list_external_profiles(spec)
        self.assertEqual(total, 1)

        spec = ProfileFilterSpec(tenant_id=self.tenant, professional_title="高级工程师")
        total, _ = list_external_profiles(spec)
        self.assertEqual(total, 1)

    def test_pagination(self):
        spec = ProfileFilterSpec(tenant_id=self.tenant, page=1, page_size=1)
        total, items = list_external_profiles(spec)
        self.assertEqual(total, 2)
        self.assertEqual(len(items), 1)

    def test_scope_college(self):
        # 学院范围：只有该学院有 engagement 的 profile 可见（§89）
        from hr_external.context import HrExternalRequestContext, HrExternalScope

        ctx = HrExternalRequestContext(
            tenant_id=self.tenant,
            scope=HrExternalScope(scope_type="COLLEGE", org_id=42),
        )
        # 给 profile_a 建一个 active engagement（org=42）
        eng = EngagementService().create_engagement(
            EngagementCreateInput(
                tenant_id=self.tenant,
                person_id=self.p1.id,
                profile_id=self.profile_a.id,
                category_id=self.profile_a.primary_category.id,
                host_organization_id=42,
                start_at=date(2026, 9, 1),
                end_at=date(2027, 8, 31),
            )
        )
        eng.status = ExternalEngagementStatus.ACTIVE
        eng.save()

        spec = ProfileFilterSpec(tenant_id=self.tenant)
        total, items = list_external_profiles(spec, ctx=ctx)
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["legalName"], "张三")


class IdentityMatchServiceTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson
        from hr_staff.services.person_identity_service import PersonIdentityService

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.service = IdentityMatchService()

        # 建立带证件的 Person + profile
        person = PersonIdentityService().create_person_with_identity(
            tenant_id=self.tenant,
            legal_name="王工",
            document_number="110101199001011234",
        )
        ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=person.id,
            source_organization_name="XX集团",
        )
        self.person = person

    def test_exact_match_by_document(self):
        result = self.service.match(
            tenant_id=self.tenant,
            document_number="110101199001011234",
            legal_name="王工",
        )
        self.assertEqual(result.level, IdentityMatchLevel.EXACT_MATCH)
        self.assertEqual(result.existing_person_id, str(self.person.id))
        self.assertIsNotNone(result.existing_profile_id)

    def test_possible_match_by_name_and_source(self):
        result = self.service.match(
            tenant_id=self.tenant,
            legal_name="王工",
            source_organization="XX集团",
        )
        self.assertEqual(result.level, IdentityMatchLevel.POSSIBLE_MATCH)

    def test_no_match(self):
        result = self.service.match(
            tenant_id=self.tenant, legal_name="不存在的名字"
        )
        self.assertEqual(result.level, IdentityMatchLevel.NO_MATCH)

    def test_insufficient_data(self):
        result = self.service.match(tenant_id=self.tenant)
        self.assertEqual(result.level, IdentityMatchLevel.INSUFFICIENT_DATA)


class ImportServiceTests(TestCase):
    def setUp(self):
        self.tenant = 101
        self.service = ImportService()

    def _csv_bytes(self):
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=["legalName", "documentNumber", "sourceOrganizationName"],
        )
        writer.writeheader()
        writer.writerow(
            {"legalName": "张三", "documentNumber": "110101199001011234", "sourceOrganizationName": "XX集团"}
        )
        writer.writerow(
            {"legalName": "", "documentNumber": "12", "sourceOrganizationName": ""}
        )
        return buf.getvalue().encode("utf-8")

    def test_csv_staging_and_validation(self):
        job = self.service.create_job(
            tenant_id=self.tenant, job_type="PROFILE", file_name="profiles.csv"
        )
        self.assertEqual(
            self.service.parse_csv_to_rows(
                job, self._csv_bytes(), tenant_id=self.tenant
            ),
            2,
        )
        self.assertEqual(job.rows.count(), 2)

        def validator(raw):
            issues = []
            if not (raw.get("legalName") or "").strip():
                issues.append("legalName:必填")
            if raw.get("documentNumber") and len(str(raw["documentNumber"])) < 6:
                issues.append("documentNumber:证件号过短")
            return issues

        job = self.service.validate_job(job, validator, tenant_id=self.tenant)
        self.assertEqual(job.status, "VALIDATION_FAILED")
        self.assertEqual(job.success_count, 1)
        self.assertEqual(job.failed_count, 1)

    def test_xlsx_bad_file_rejected(self):
        job = self.service.create_job(
            tenant_id=self.tenant, job_type="PROFILE", file_name="profiles.xlsx"
        )
        # 坏文件（非 XLSX 字节）→ ImportValidationError，不静默
        with self.assertRaises(ImportValidationError):
            self.service.parse_spreadsheet_to_rows(
                job, b"this is not an xlsx", tenant_id=self.tenant
            )

    def test_xlsx_parse_and_commit_end_to_end(self):
        """XLSX → 同一 staging/validate/confirm/execute 链路过账本（任务 4）。"""
        from io import BytesIO

        from openpyxl import Workbook

        from hr_external.models import HrExternalTeacherProfile

        CategoryService().ensure_default_categories(self.tenant)
        wb = Workbook()
        ws = wb.active
        ws.append(["legalName", "documentNumber", "sourceOrganizationName"])
        ws.append(["王教授", "110101199001011234", "XX智造"])
        ws.append(["", "12", ""])  # 非法行：缺 legalName + 证件过短
        buf = BytesIO()
        wb.save(buf)

        job = self.service.create_job(
            tenant_id=self.tenant, job_type="PROFILE", file_name="profiles.xlsx"
        )
        self.assertEqual(
            self.service.parse_spreadsheet_to_rows(
                job, buf.getvalue(), tenant_id=self.tenant
            ),
            2,
        )
        self.assertEqual(job.rows.count(), 2)

        def validator(raw):
            issues = []
            if not (raw.get("legalName") or "").strip():
                issues.append("legalName:必填")
            if raw.get("documentNumber") and len(str(raw["documentNumber"])) < 6:
                issues.append("documentNumber:证件号过短")
            return issues

        job = self.service.validate_job(job, validator, tenant_id=self.tenant)
        self.assertEqual(job.status, "VALIDATION_FAILED")
        self.assertEqual(job.success_count, 1)
        self.assertEqual(job.failed_count, 1)

        job = self.service.confirm_job(job, tenant_id=self.tenant)
        job = self.service.execute_commit(job, tenant_id=self.tenant)
        self.assertEqual(job.status, "PARTIAL_FAILED")  # 1 成功 1 失败（精确失败行账本）
        self.assertEqual(
            HrExternalTeacherProfile.objects.filter(
                tenant_id=self.tenant, source_organization_name="XX智造"
            ).count(),
            1,
        )
        self.assertEqual(job.rows.filter(status="COMMITTED").count(), 1)
        self.assertEqual(job.rows.filter(status="FAILED").count(), 0)  # INVALID 保留在 validate 阶段

    def test_confirm_marks_committing_not_fake_complete(self):
        # confirm 只置 COMMITTING，不伪装完成（00 §32）
        job = self.service.create_job(
            tenant_id=self.tenant, job_type="PROFILE", file_name="profiles.csv"
        )
        job = self.service.confirm_job(job, tenant_id=self.tenant)
        self.assertEqual(job.status, "COMMITTING")

    def test_execute_commit_end_to_end(self):
        """upload → validate → confirm → execute → COMPLETED + Profile 创建（分批事务真实执行）。"""
        from hr_external.models import HrExternalTeacherProfile

        CategoryService().ensure_default_categories(self.tenant)
        job = self.service.create_job(
            tenant_id=self.tenant, job_type="PROFILE", file_name="profiles.csv"
        )
        self.service.parse_csv_to_rows(
            job, self._csv_bytes(), tenant_id=self.tenant
        )

        def validator(raw):
            issues = []
            if not (raw.get("legalName") or "").strip():
                issues.append("legalName:必填")
            if raw.get("documentNumber") and len(str(raw["documentNumber"])) < 6:
                issues.append("documentNumber:证件号过短")
            return issues

        job = self.service.validate_job(job, validator, tenant_id=self.tenant)
        self.assertEqual(job.status, "VALIDATION_FAILED")
        self.assertEqual(job.success_count, 1)  # 第一行合法
        self.assertEqual(job.failed_count, 1)  # 第二行缺 legalName

        job = self.service.confirm_job(job, tenant_id=self.tenant)
        job = self.service.execute_commit(job, tenant_id=self.tenant)
        # 1 行 VALID commit 成功；1 行 validate 阶段 INVALID 保留失败
        self.assertEqual(job.status, "PARTIAL_FAILED")
        self.assertEqual(job.success_count, 1)
        self.assertEqual(job.failed_count, 1)
        self.assertEqual(
            HrExternalTeacherProfile.objects.filter(
                tenant_id=self.tenant,
                source_organization_name="XX集团",
            ).count(),
            1,
        )
        committed_rows = job.rows.filter(status="COMMITTED").count()
        self.assertEqual(committed_rows, 1)
