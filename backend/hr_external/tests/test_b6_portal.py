"""B6 · 外聘本人门户契约测试（总册 §90/00 §134）。"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from hr_external.models import HrExternalPortalToken
from hr_external.services.category_service import CategoryService
from hr_external.services.portal_service import (
    PortalService,
    PortalTokenInvalid,
)
from hr_external.services.profile_service import ProfileService


class PortalTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="冯教授")
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="INDUSTRY_PROFESSOR",
        )
        self.service = PortalService()

    def test_issue_token_stores_hash_not_plain(self):
        raw, token = self.service.issue_token(
            tenant_id=self.tenant, external_profile_id=self.profile.id, issued_by=1
        )
        self.assertNotEqual(raw, token.token_hash)
        self.assertEqual(token.status, "ACTIVE")

    def test_resolve_token_returns_profile(self):
        raw, _ = self.service.issue_token(
            tenant_id=self.tenant, external_profile_id=self.profile.id
        )
        profile = self.service.resolve_token(raw=raw)
        self.assertEqual(str(profile.id), str(self.profile.id))

    def test_invalid_token_rejected(self):
        with self.assertRaises(PortalTokenInvalid):
            self.service.resolve_token(raw="not-a-valid-token")

    def test_expired_token_rejected(self):
        raw, token = self.service.issue_token(
            tenant_id=self.tenant, external_profile_id=self.profile.id
        )
        token.expires_at = timezone.now() - timedelta(seconds=1)
        token.save(update_fields=["expires_at"])
        with self.assertRaises(PortalTokenInvalid):
            self.service.resolve_token(raw=raw)
        token.refresh_from_db()
        self.assertEqual(token.status, "EXPIRED")

    def test_me_returns_self_data_only(self):
        raw, _ = self.service.issue_token(
            tenant_id=self.tenant, external_profile_id=self.profile.id
        )
        profile = self.service.resolve_token(raw=raw)
        data = self.service.me(profile=profile)
        self.assertEqual(data["profile"]["legalName"], "冯教授")
        self.assertIn("tasks", data)
        self.assertIn("workload", data)
        # §90：不暴露敏感合规内部结论
        self.assertNotIn("ethicsStatus", data["profile"])
        self.assertNotIn("identityVerificationStatus", data["profile"])
