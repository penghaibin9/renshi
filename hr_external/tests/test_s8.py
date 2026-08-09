"""S8 · 续聘与退出契约测试。

覆盖（总册 §58-70）：
- 续聘 Review 创建（Engagement→REVIEW_DUE）；RENEW 创建新 Engagement（不直接改 end_at，§61/§138.11）；
- DO_NOT_RENEW → EXPIRED；CONVERT_TO_REGULAR → EXITING（转正式走 HR04/05/03，不改 worker_kind，§62）；
- Exit Case 创建（Engagement→EXITING）；finalize → Engagement ENDED + 权限回收请求（§66）+ 历史保留（§70）；
- 一个 Engagement 退出不误杀另一个（§138.14，access 聚合）。
"""

from datetime import date

from django.test import TestCase

from hr_external.constants import (
    ExternalEngagementStatus,
    RenewalDecision,
    RenewalReviewStatus,
)
from hr_external.models import (
    HrExternalAccessGrant,
    HrExternalEngagement,
    HrExternalExitCase,
    HrExternalProvisioningRequest,
    HrExternalRenewalReview,
)
from hr_external.services.access_service import AccessService
from hr_external.services.category_service import CategoryService
from hr_external.services.engagement_service import EngagementService, EngagementCreateInput
from hr_external.services.exit_service import ExitService
from hr_external.services.profile_service import ProfileService
from hr_external.services.renewal_service import RenewalService


class RenewalTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="刘教授")
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="INDUSTRY_PROFESSOR",
        )
        self.eng = EngagementService().create_engagement(
            EngagementCreateInput(
                tenant_id=self.tenant,
                person_id=self.person.id,
                profile_id=self.profile.id,
                category_id=self.profile.primary_category.id,
                host_organization_id=1,
                start_at=date(2025, 9, 1),
                end_at=date(2026, 8, 31),
            )
        )
        self.eng.status = ExternalEngagementStatus.ACTIVE
        self.eng.save()
        self.renewal = RenewalService()

    def test_review_creation_marks_review_due(self):
        review = self.renewal.create_review(
            tenant_id=self.tenant,
            engagement_id=self.eng.id,
            review_due_at=date(2026, 6, 1),
            task_completion_summary="课程完成",
        )
        self.assertEqual(review.status, RenewalReviewStatus.DRAFT)
        self.eng.refresh_from_db()
        self.assertEqual(self.eng.status, ExternalEngagementStatus.REVIEW_DUE)

    def test_renew_creates_new_engagement_not_edit_end(self):
        review = self.renewal.create_review(
            tenant_id=self.tenant, engagement_id=self.eng.id, review_due_at=date(2026, 6, 1)
        )
        review.status = RenewalReviewStatus.IN_REVIEW
        review.save(update_fields=["status", "updated_at"])
        decision = self.renewal.decide(
            review,
            decision=RenewalDecision.RENEW,
            decided_by=1,
            next_start=date(2026, 9, 1),
            next_end=date(2027, 8, 31),
        )
        self.assertEqual(decision, RenewalDecision.RENEW)
        # 原 Engagement end_at 未被修改（§61/§138.11）
        self.eng.refresh_from_db()
        self.assertEqual(self.eng.end_at, date(2026, 8, 31))
        # 新 Engagement DRAFT 待 S5 审批链
        review.refresh_from_db()
        new_eng = HrExternalEngagement.objects.get(id=review.next_engagement_id_id)
        self.assertEqual(new_eng.status, ExternalEngagementStatus.DRAFT)
        self.assertEqual(new_eng.start_at, date(2026, 9, 1))

    def test_do_not_renew_marks_expired(self):
        review = self.renewal.create_review(
            tenant_id=self.tenant, engagement_id=self.eng.id, review_due_at=date(2026, 6, 1)
        )
        review.status = RenewalReviewStatus.IN_REVIEW
        review.save(update_fields=["status", "updated_at"])
        self.renewal.decide(review, decision=RenewalDecision.DO_NOT_RENEW, decided_by=1)
        self.eng.refresh_from_db()
        self.assertEqual(self.eng.status, ExternalEngagementStatus.EXPIRED)

    def test_convert_to_regular_marks_exiting(self):
        review = self.renewal.create_review(
            tenant_id=self.tenant, engagement_id=self.eng.id, review_due_at=date(2026, 6, 1)
        )
        review.status = RenewalReviewStatus.IN_REVIEW
        review.save(update_fields=["status", "updated_at"])
        self.renewal.decide(
            review, decision=RenewalDecision.CONVERT_TO_REGULAR_HR_PROCESS, decided_by=1
        )
        self.eng.refresh_from_db()
        # 转正式走 HR04/05/03 正式链（§62），Engagement 进入 EXITING
        self.assertEqual(self.eng.status, ExternalEngagementStatus.EXITING)

    def test_change_category_creates_new_engagement_with_new_category(self):
        """CHANGE_CATEGORY：新聘期类别切换为指定类别（§60）。"""
        from hr_external.models import HrExternalCategory

        review = self.renewal.create_review(
            tenant_id=self.tenant, engagement_id=self.eng.id, review_due_at=date(2026, 6, 1)
        )
        review.status = RenewalReviewStatus.IN_REVIEW
        review.save(update_fields=["status", "updated_at"])

        new_category = HrExternalCategory.objects.get(
            tenant_id=self.tenant, code="PART_TIME_TEACHER"
        )
        self.renewal.decide(
            review,
            decision=RenewalDecision.CHANGE_CATEGORY,
            decided_by=1,
            next_start=date(2026, 9, 1),
            next_end=date(2027, 8, 31),
            next_category_id=new_category.id,
        )
        review.refresh_from_db()
        new_eng = HrExternalEngagement.objects.get(id=review.next_engagement_id_id)
        self.assertEqual(str(new_eng.category_id_id), str(new_category.id))
        # 原聘期 end_at 不被修改（§61/§138.11）
        self.eng.refresh_from_db()
        self.assertEqual(self.eng.end_at, date(2026, 8, 31))

    def test_change_category_invalid_raises(self):
        """CHANGE_CATEGORY 指定不存在的类别 → 拒绝（RenewalStateConflict）。"""
        import uuid

        review = self.renewal.create_review(
            tenant_id=self.tenant, engagement_id=self.eng.id, review_due_at=date(2026, 6, 1)
        )
        review.status = RenewalReviewStatus.IN_REVIEW
        review.save(update_fields=["status", "updated_at"])
        from hr_external.services.renewal_service import RenewalStateConflict

        with self.assertRaises(RenewalStateConflict):
            self.renewal.decide(
                review,
                decision=RenewalDecision.CHANGE_CATEGORY,
                decided_by=1,
                next_category_id=uuid.uuid4(),  # 不存在的类别
            )


class ExitTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="郑工")
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="EXTERNAL_TEACHER",
        )
        self.eng = EngagementService().create_engagement(
            EngagementCreateInput(
                tenant_id=self.tenant,
                person_id=self.person.id,
                profile_id=self.profile.id,
                category_id=self.profile.primary_category.id,
                host_organization_id=1,
                start_at=date(2025, 9, 1),
                end_at=date(2026, 8, 31),
            )
        )
        self.eng.status = ExternalEngagementStatus.ACTIVE
        self.eng.save()
        self.service = ExitService()

    def test_exit_flow_ends_engagement_and_revokes(self):
        AccessService().provision_engagement_access(tenant_id=self.tenant, engagement=self.eng)
        case = self.service.create_exit_case(
            tenant_id=self.tenant,
            engagement_id=self.eng.id,
            exit_reason="TERM_COMPLETED",
            planned_end_at=date(2026, 8, 31),
        )
        self.eng.refresh_from_db()
        self.assertEqual(self.eng.status, ExternalEngagementStatus.EXITING)
        self.assertEqual(case.status, "PLANNED")

        case.status = "READY_TO_EXIT"
        case.save(update_fields=["status", "updated_at"])
        self.service.start_exit(case)
        case = self.service.finalize_exit(case, tenant_id=self.tenant)

        self.eng.refresh_from_db()
        self.assertEqual(self.eng.status, ExternalEngagementStatus.ENDED)
        # 权限回收请求已发起（§66）
        self.assertTrue(
            HrExternalProvisioningRequest.objects.filter(
                tenant_id=self.tenant,
                engagement_id=self.eng,
                operation="REVOKE",
            ).exists()
        )
        # 历史保留（§70）：Engagement 记录仍在（不删除）
        self.assertTrue(HrExternalEngagement.objects.filter(id=self.eng.id).exists())

    def test_exit_draft_engagement_blocked(self):
        """DRAFT/未生效聘期不可退出（复审修复）。"""
        from hr_external.services.exit_service import ExitBlocked

        self.eng.status = ExternalEngagementStatus.DRAFT
        self.eng.save()
        with self.assertRaises(ExitBlocked):
            self.service.create_exit_case(
                tenant_id=self.tenant,
                engagement_id=self.eng.id,
                exit_reason="OTHER",
                planned_end_at=date(2026, 8, 31),
            )

    def test_exit_ended_engagement_blocked(self):
        """已结束聘期不可再次退出。"""
        from hr_external.services.exit_service import ExitBlocked

        self.eng.status = ExternalEngagementStatus.ENDED
        self.eng.save()
        with self.assertRaises(ExitBlocked):
            self.service.create_exit_case(
                tenant_id=self.tenant,
                engagement_id=self.eng.id,
                exit_reason="OTHER",
                planned_end_at=date(2026, 8, 31),
            )

    def test_exit_does_not_kill_other_engagement(self):
        # 两个并行 engagement（不同 person 简化验证聚合回收只影响本聘期）
        from hr_staff.models import HrPerson

        person2 = HrPerson.objects.create(tenant_id=self.tenant, legal_name="孙工")
        profile2 = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=person2.id,
            primary_category_code="INDUSTRY_ADJUNCT",
        )
        eng2 = EngagementService().create_engagement(
            EngagementCreateInput(
                tenant_id=self.tenant,
                person_id=person2.id,
                profile_id=profile2.id,
                category_id=profile2.primary_category.id,
                host_organization_id=2,
                start_at=date(2026, 9, 1),
                end_at=date(2026, 12, 31),
            )
        )
        eng2.status = ExternalEngagementStatus.ACTIVE
        eng2.save()

        AccessService().provision_engagement_access(tenant_id=self.tenant, engagement=self.eng)
        AccessService().provision_engagement_access(tenant_id=self.tenant, engagement=eng2)

        case = self.service.create_exit_case(
            tenant_id=self.tenant,
            engagement_id=self.eng.id,
            exit_reason="TERM_COMPLETED",
            planned_end_at=date(2026, 8, 31),
        )
        case.status = "READY_TO_EXIT"
        case.save(update_fields=["status", "updated_at"])
        self.service.finalize_exit(case, tenant_id=self.tenant)

        # eng 的 grant 被回收请求，eng2 的 grant 保持（§138.14/§99）
        eng2_grants = HrExternalAccessGrant.objects.filter(engagement_id=eng2)
        self.assertEqual(eng2_grants.count(), 3)
        self.assertTrue(all(g.status in ("PENDING", "GRANTED") for g in eng2_grants))
