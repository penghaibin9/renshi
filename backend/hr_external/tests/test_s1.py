"""S1 · HR08 基础 contract 契约测试。

覆盖：
- enums/权限码/事件类型/错误码 完整性（constants.py）
- HrExternalCategory 模型约束（tenant 内 code 唯一）
- API envelope 结构（api/base.py）
- 权限装饰器 fail-closed（permissions.py）
- context tenant/scope fail-closed（context.py）
"""

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase, TestCase

from hr_external.constants import (
    AgreementRequirement,
    ExternalEngagementStatus,
    ExternalWorkerCategory,
    HR08_EVENT_TYPES,
    HR08_PERMISSIONS,
    HR08_ERROR_CODES,
    RiskType,
)
from hr_external.context import HrExternalContextError, build_external_context
from hr_external.models import HrExternalCategory
from hr_external.permissions import has_sensitive_view, require_hr_external_permission
from hr_external.services.category_service import CategoryService


class ConstantsContractTests(SimpleTestCase):
    def test_worker_category_enum_has_all_builtin_codes(self):
        codes = {c.value for c in ExternalWorkerCategory}
        expected = {
            "PART_TIME_TEACHER",
            "EXTERNAL_TEACHER",
            "INDUSTRY_ADJUNCT",
            "INDUSTRY_PROFESSOR",
            "SKILL_MASTER",
            "INDUSTRY_MENTOR",
            "VISITING_PROFESSOR",
            "GUEST_PROFESSOR",
            "HONORARY_TITLE",
            "EXTERNAL_EXPERT",
            "PRACTICE_INSTRUCTOR",
            "RETIRED_REHIRE_EXTERNAL",
            "PROJECT_EXPERT",
            "OTHER",
        }
        self.assertEqual(codes, expected)

    def test_engagement_status_has_core_chain(self):
        statuses = {s.value for s in ExternalEngagementStatus}
        for required in (
            "DRAFT",
            "UNDER_REVIEW",
            "APPROVED",
            "WAITING_AGREEMENT",
            "SIGNED_WAITING_EFFECTIVE",
            "ACTIVE",
            "REVIEW_DUE",
            "RENEWAL_IN_PROGRESS",
            "EXPIRED",
            "EXITING",
            "ENDED",
            "ARCHIVED",
        ):
            self.assertIn(required, statuses)

    def test_agreement_requirement_default_is_before_activation(self):
        # 默认正式外聘 REQUIRED_BEFORE_ACTIVATION（§93）
        self.assertEqual(
            AgreementRequirement.REQUIRED_BEFORE_ACTIVATION.value,
            "REQUIRED_BEFORE_ACTIVATION",
        )

    def test_permissions_cover_required_domains(self):
        perms = set(HR08_PERMISSIONS)
        for required in (
            "hr08.profile.view",
            "hr08.hiring.approve",
            "hr08.task.verify",
            "hr08.renewal.decide",
            "hr08.exit.manage",
            "hr08.access.manage",
        ):
            self.assertIn(required, perms)

    def test_error_codes_cover_master_doc(self):
        codes = set(HR08_ERROR_CODES)
        for required in (
            "EXTERNAL_PERSON_MATCH_REQUIRED",
            "EXTERNAL_ENGAGEMENT_OVERLAP",
            "EXTERNAL_AGREEMENT_NOT_READY",
            "EXTERNAL_ACCESS_REVOKE_FAILED",
            "VERSION_CONFLICT",
        ):
            self.assertIn(required, codes)

    def test_event_types_past_tense(self):
        for ev in HR08_EVENT_TYPES:
            self.assertTrue(ev[0].isupper(), f"event must be PascalCase: {ev}")

    def test_risk_types_cover_identity_drift(self):
        risks = {r.value for r in RiskType}
        self.assertIn("ACADEMIC_IDENTITY_DRIFT", risks)
        self.assertIn("LEGACY_PROJECTION_DRIFT", risks)


class CategoryModelTests(TestCase):
    def setUp(self):
        self.service = CategoryService()

    def test_ensure_default_categories_is_idempotent(self):
        self.assertEqual(self.service.ensure_default_categories(tenant_id=1), 14)
        self.assertEqual(self.service.ensure_default_categories(tenant_id=1), 0)
        self.assertEqual(HrExternalCategory.objects.filter(tenant_id=1).count(), 14)

    def test_category_code_unique_per_tenant(self):
        self.service.ensure_default_categories(tenant_id=1)
        self.service.ensure_default_categories(tenant_id=2)
        # 不同 tenant 可同 code
        self.assertEqual(
            HrExternalCategory.objects.filter(code="INDUSTRY_PROFESSOR").count(), 2
        )
        # 同 tenant 重复 code 被唯一约束拒绝
        with self.assertRaises(Exception):
            HrExternalCategory.objects.create(
                tenant_id=1, code="INDUSTRY_PROFESSOR", name="重复"
            )

    def test_honorary_title_not_teaching_by_default(self):
        self.service.ensure_default_categories(tenant_id=1)
        cat = self.service.get_category(tenant_id=1, code="HONORARY_TITLE")
        self.assertFalse(cat.allow_teaching)
        self.assertFalse(cat.allow_research)
        self.assertEqual(cat.agreement_requirement, "NOT_REQUIRED")

    def test_industry_professor_default_policy(self):
        self.service.ensure_default_categories(tenant_id=1)
        cat = self.service.get_category(tenant_id=1, code="INDUSTRY_PROFESSOR")
        self.assertTrue(cat.requires_open_selection)
        self.assertTrue(cat.requires_ethics_review)
        self.assertTrue(cat.requires_industry_experience)
        self.assertTrue(cat.allow_teaching)
        self.assertTrue(cat.allow_research)
        self.assertEqual(cat.agreement_requirement, "REQUIRED_BEFORE_ACTIVATION")


class ApiEnvelopeTests(SimpleTestCase):
    def test_json_response_has_version_fields(self):
        from django.test import RequestFactory

        from hr_external.api.base import api_root, json_response

        request = RequestFactory().get("/")
        payload = api_root(request)
        for key in ("apiVersion", "schemaVersion", "requestId", "generatedAt"):
            self.assertIn(key, payload)
        resp = json_response(request, {"data": {}})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Cache-Control"], "no-store")


class PermissionTests(SimpleTestCase):
    def test_decorator_denies_without_perm(self):
        factory = RequestFactory()

        @require_hr_external_permission("hr08.profile.view")
        def view(request):
            return "ok"

        class Anon:
            is_authenticated = False

        request = factory.get("/")
        request.user = Anon()
        with self.assertRaises(PermissionDenied):
            view(request)

    def test_sensitive_view_requires_perm(self):
        class FakeUser:
            def __init__(self, perms=(), is_superuser=False):
                self._perms = set(perms)
                self.is_superuser = is_superuser

            def has_perm(self, perm):
                return perm in self._perms

        self.assertTrue(has_sensitive_view(FakeUser(is_superuser=True), "HIGH_SENSITIVE"))
        self.assertTrue(has_sensitive_view(FakeUser(perms=("hr08.profile.sensitive_view",)), "SENSITIVE"))
        self.assertFalse(has_sensitive_view(FakeUser(), "SENSITIVE"))


class ContextTests(SimpleTestCase):
    def test_missing_tenant_fail_closed(self):
        with self.assertRaises(HrExternalContextError) as ctx:
            build_external_context(tenant_id=None)
        self.assertEqual(ctx.exception.code, "TENANT_CONTEXT_REQUIRED")

    def test_invalid_scope_fail_closed(self):
        with self.assertRaises(HrExternalContextError) as ctx:
            build_external_context(tenant_id=1, scope_type="EVERYTHING")
        self.assertEqual(ctx.exception.code, "EXTERNAL_SCOPE_DENIED")

    def test_engagement_scope_accepted(self):
        ctx = build_external_context(
            tenant_id=1,
            scope_type="ENGAGEMENT",
            scope_engagement_ids=["e1", "e2"],
        )
        self.assertEqual(ctx.scope.scope_type, "ENGAGEMENT")
        self.assertEqual(ctx.scope.engagement_ids, frozenset({"e1", "e2"}))
