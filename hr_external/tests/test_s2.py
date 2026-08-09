"""S2 · Authority Models 契约测试。

覆盖（总册 §16-23/§33-37/§66-68/§103-105）：
- Profile：tenant 唯一 person / tenant 唯一 external_teacher_no / 身份根复用 hr_staff.HrPerson；
- Engagement：日期 CheckConstraint / 编号唯一 / 一人多 Engagement（非重叠）/ 重叠阻断 /
  tenant FK 一致性；
- 状态机转换守卫；
- Agreement gate（§42/§93）：NOT_REQUIRED 放行；REQUIRED_BEFORE_ACTIVATION 需 SIGNED/ACTIVE；
- Provider 契约：HR03 PersonProvider 真实可用；HR07 AgreementProvider 占位 UNAVAILABLE（§13 不 silent fallback）。
"""

from datetime import date

from django.db import IntegrityError
from django.test import TestCase

from hr_external.constants import (
    AgreementProviderStatus,
    AgreementRequirement,
    ExternalEngagementStatus,
)
from hr_external.integrations.hr03 import PersonProvider
from hr_external.integrations.hr07 import AgreementProvider
from hr_external.models import HrExternalEngagement, HrExternalTeacherProfile
from hr_external.services.category_service import CategoryService
from hr_external.services.engagement_service import (
    CrossTenantReference,
    EngagementOverlap,
    EngagementService,
    EngagementCreateInput,
)
from hr_external.services.profile_service import (
    ExternalTeacherNumberService,
    ProfileService,
)


class ProfileModelTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        self.person_a = HrPerson.objects.create(tenant_id=self.tenant, legal_name="张三")
        self.person_b = HrPerson.objects.create(tenant_id=self.tenant, legal_name="李四")
        self.other_tenant_person = HrPerson.objects.create(
            tenant_id=999, legal_name="王五"
        )
        self.service = ProfileService()
        self.number_service = ExternalTeacherNumberService()

    def test_profile_uses_hr03_person_as_identity_root(self):
        # 身份根必须是 hr_staff.HrPerson；严禁自建 ExternalPerson
        profile = self.service.create_profile(
            tenant_id=self.tenant,
            person_id=self.person_a.id,
            source_organization_name="XX集团",
        )
        self.assertEqual(str(profile.person_id_id), str(self.person_a.id))
        from hr_staff.models import HrPerson

        self.assertIsInstance(profile.person_id, HrPerson)

    def test_tenant_scoped_external_no_and_person_unique(self):
        self.service.create_profile(tenant_id=self.tenant, person_id=self.person_a.id)
        # 同 tenant 同 person → 拒绝
        with self.assertRaises(Exception):
            self.service.create_profile(
                tenant_id=self.tenant, person_id=self.person_a.id
            )
        # 同 tenant 同 external_no（手工指定冲突）→ 拒绝
        with self.assertRaises(Exception):
            HrExternalTeacherProfile.objects.create(
                tenant_id=self.tenant,
                person_id=self.person_b,
                external_teacher_no="EXT2026000001",
            )
        # 不同 tenant 可复用同 person（跨学校不自动关联，§6.2/§138.16）
        p = self.service.create_profile(
            tenant_id=999, person_id=self.other_tenant_person.id
        )
        self.assertEqual(p.tenant_id, 999)

    def test_number_service_sequence(self):
        no1 = self.number_service.next_external_no(self.tenant)
        self.service.create_profile(
            tenant_id=self.tenant,
            person_id=self.person_a.id,
        )
        no2 = self.number_service.next_external_no(self.tenant)
        self.assertEqual(no1, f"EXT{date.today().year}000001")
        self.assertEqual(no2, f"EXT{date.today().year}000002")


class EngagementModelTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="赵工")
        CategoryService().ensure_default_categories(self.tenant)
        self.category = CategoryService().get_category(self.tenant, "INDUSTRY_PROFESSOR")
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="INDUSTRY_PROFESSOR",
            source_organization_name="XX智能制造",
        )
        self.service = EngagementService()

    def _input(self, start, end=None, status=ExternalEngagementStatus.DRAFT):
        return EngagementCreateInput(
            tenant_id=self.tenant,
            person_id=self.person.id,
            profile_id=self.profile.id,
            category_id=self.category.id,
            host_organization_id=1,
            start_at=start,
            end_at=end,
        )

    def test_create_engagement_success(self):
        eng = self.service.create_engagement(
            self._input(date(2026, 9, 1), date(2027, 8, 31))
        )
        self.assertEqual(eng.status, ExternalEngagementStatus.DRAFT)
        self.assertEqual(eng.agreement_requirement, "REQUIRED_BEFORE_ACTIVATION")

    def test_dates_constraint(self):
        with self.assertRaises(IntegrityError):
            HrExternalEngagement.objects.create(
                tenant_id=self.tenant,
                engagement_no="BAD",
                person_id=self.person,
                external_profile_id=self.profile,
                category_id=self.category,
                host_organization_id=1,
                start_at=date(2027, 8, 31),
                end_at=date(2026, 9, 1),
            )

    def test_multiple_non_overlapping_engagements_allowed(self):
        eng1 = self.service.create_engagement(
            self._input(date(2026, 9, 1), date(2027, 8, 31))
        )
        eng1.status = ExternalEngagementStatus.ACTIVE
        eng1.save()
        eng2 = self.service.create_engagement(
            self._input(date(2027, 9, 1), date(2028, 8, 31))
        )
        self.assertNotEqual(eng1.id, eng2.id)

    def test_overlap_blocked(self):
        eng1 = self.service.create_engagement(
            self._input(date(2026, 9, 1), date(2027, 8, 31))
        )
        eng1.status = ExternalEngagementStatus.ACTIVE
        eng1.save()
        with self.assertRaises(EngagementOverlap):
            self.service.create_engagement(
                self._input(date(2027, 3, 1), date(2028, 2, 28))
            )

    def test_cross_tenant_reference_blocked(self):
        from hr_staff.models import HrPerson

        other_person = HrPerson.objects.create(tenant_id=999, legal_name="外校")
        with self.assertRaises(CrossTenantReference):
            self.service.create_engagement(
                EngagementCreateInput(
                    tenant_id=self.tenant,
                    person_id=other_person.id,
                    profile_id=self.profile.id,
                    category_id=self.category.id,
                    host_organization_id=1,
                    start_at=date(2026, 9, 1),
                    end_at=date(2027, 8, 31),
                )
            )

    def test_status_transition_guard(self):
        self.assertTrue(
            EngagementService.validate_transition(
                ExternalEngagementStatus.DRAFT, ExternalEngagementStatus.UNDER_REVIEW
            )
        )
        self.assertFalse(
            EngagementService.validate_transition(
                ExternalEngagementStatus.DRAFT, ExternalEngagementStatus.ENDED
            )
        )

    def test_agreement_gate(self):
        eng = self.service.create_engagement(
            self._input(date(2026, 9, 1), date(2027, 8, 31))
        )
        # REQUIRED_BEFORE_ACTIVATION + UNAVAILABLE → 不通过
        self.assertFalse(self.service.agreement_gate_passed(eng))
        # SIGNED → 通过
        eng.agreement_status = AgreementProviderStatus.SIGNED.value
        self.assertTrue(self.service.agreement_gate_passed(eng))
        # NOT_REQUIRED → 通过
        eng.agreement_requirement = AgreementRequirement.NOT_REQUIRED.value
        eng.agreement_status = AgreementProviderStatus.UNAVAILABLE.value
        self.assertTrue(self.service.agreement_gate_passed(eng))


class ProviderContractTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="孙工")

    def test_person_provider_by_id(self):
        result = PersonProvider().by_id(tenant_id=self.tenant, person_id=self.person.id)
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.data["legalName"], "孙工")

    def test_person_provider_identity_match_hard(self):
        from hr_staff.services.person_identity_service import PersonIdentityService

        PersonIdentityService().create_person_with_identity(
            tenant_id=self.tenant,
            legal_name="钱工",
            document_number="110101199001011234",
        )
        result = PersonProvider().identity_match(
            tenant_id=self.tenant,
            document_number="110101199001011234",
            legal_name="钱工",
        )
        self.assertEqual(result.data["level"], "HARD_MATCH")

    def test_person_provider_requires_tenant(self):
        with self.assertRaises(ValueError):
            PersonProvider().by_id(tenant_id=None, person_id=self.person.id)

    def test_agreement_provider_placeholder_unavailable(self):
        # # [总控占位] HR07 未交付：必须 UNAVAILABLE，不 silent fallback legacy（00 §13）
        result = AgreementProvider().resolve_agreement(
            tenant_id=self.tenant, agreement_type_code="EXTERNAL_EXPERT"
        )
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertEqual(result.error_code, "PROVIDER_UNAVAILABLE")
