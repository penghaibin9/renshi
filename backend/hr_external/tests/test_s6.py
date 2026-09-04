"""S6 · IAM/教务集成契约测试。

覆盖（总册 §94-99/§96/§97/§104/§105）：
- AccessGrant provisioning：activation 后创建 scoped grants + GRANT requests；expires_at <= end_at + grace；
- 回收：revoke 只影响本 engagement 的 grants（§99/§138.14）；
- 撤权失败 → Risk=CRITICAL（§105）；
- 对账：ended engagement 的 academic identity / access grant 漂移检测。
"""

from datetime import date, datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from hr_external.constants import (
    AccessGrantStatus,
    AcademicIdentityStatus,
    ExternalEngagementStatus,
    ProvisioningStatus,
    RiskSeverity,
)
from hr_external.models import (
    HrExternalAcademicIdentity,
    HrExternalAccessGrant,
    HrExternalEngagement,
    HrExternalLifecycleEvent,
    HrExternalProvisioningRequest,
    HrExternalServiceTask,
)
from hr_external.services.access_service import AccessScopeInvalid, AccessService
from hr_external.services.category_service import CategoryService
from hr_external.services.engagement_service import EngagementService, EngagementCreateInput
from hr_external.services.profile_service import ProfileService
from hr_external.services.reconciliation_service import ReconciliationService


class AccessLifecycleTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="周工")
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
                start_at=date(2026, 9, 1),
                end_at=date(2027, 8, 31),
            )
        )
        self.eng.status = ExternalEngagementStatus.ACTIVE
        self.eng.save()
        self.service = AccessService()

    def test_provision_creates_scoped_grants_with_expiry(self):
        grants = self.service.provision_engagement_access(tenant_id=self.tenant, engagement=self.eng)
        self.assertEqual(len(grants), 1)  # least privilege: portal only without a teaching task
        for g in grants:
            self.assertEqual(g.target_system, "EXTERNAL_PORTAL")
            # expires_at <= end_at + grace（§67）
            max_expiry = timezone.make_aware(
                datetime.combine(self.eng.end_at, datetime.min.time())
            ) + timedelta(days=7)
            self.assertLessEqual(g.expires_at, max_expiry)
        self.assertEqual(
            HrExternalProvisioningRequest.objects.filter(
                tenant_id=self.tenant, operation="GRANT"
            ).count(),
            1,
        )

    def test_provisioning_idempotency_key_unique(self):
        first = self.service.provision_engagement_access(
            tenant_id=self.tenant, engagement=self.eng
        )
        repeated = self.service.provision_engagement_access(
            tenant_id=self.tenant, engagement=self.eng
        )

        self.assertEqual(
            {grant.id for grant in repeated},
            {grant.id for grant in first},
        )
        self.assertEqual(
            HrExternalAccessGrant.objects.filter(tenant_id=self.tenant, engagement_id=self.eng).count(),
            1,
        )

    def test_academic_access_requires_authoritative_teaching_reference(self):
        HrExternalServiceTask.objects.create(
            tenant_id=self.tenant,
            engagement_id=self.eng,
            task_type="TEACHING",
            source_domain="ACADEMIC",
            source_object_type="TEACHING_ASSIGNMENT",
            source_object_id="JW-COURSE-2026-001",
            title="2026 秋季学期课程教学",
            planned_start=date(2026, 9, 1),
            owner_org_id=1,
            status="ASSIGNED",
        )

        grants = self.service.provision_engagement_access(
            tenant_id=self.tenant, engagement=self.eng
        )

        self.assertEqual({grant.target_system for grant in grants}, {"EXTERNAL_PORTAL", "ACADEMIC"})
        academic = next(grant for grant in grants if grant.target_system == "ACADEMIC")
        self.assertEqual(
            academic.scope_json["teachingTaskRefs"], ["JW-COURSE-2026-001"]
        )
        request = HrExternalProvisioningRequest.objects.get(
            tenant_id=self.tenant,
            engagement_id=self.eng,
            target_system="ACADEMIC",
            operation="GRANT",
        )
        self.assertEqual(
            request.scope_json["teachingTaskRefs"], ["JW-COURSE-2026-001"]
        )

    def test_unknown_access_policy_fails_closed(self):
        category = self.profile.primary_category
        category.access_policy_code = "UNREVIEWED_CUSTOM_POLICY"
        category.save(update_fields=["access_policy_code", "updated_at"])

        with self.assertRaises(AccessScopeInvalid):
            self.service.provision_engagement_access(
                tenant_id=self.tenant, engagement=self.eng
            )

        self.assertFalse(
            HrExternalAccessGrant.objects.filter(
                tenant_id=self.tenant, engagement_id=self.eng
            ).exists()
        )

    def test_policy_downgrade_queues_revoke_for_obsolete_grant(self):
        category = self.profile.primary_category
        category.access_policy_code = "PORTAL_LIBRARY"
        category.save(update_fields=["access_policy_code", "updated_at"])
        self.service.provision_engagement_access(
            tenant_id=self.tenant, engagement=self.eng
        )
        library = HrExternalAccessGrant.objects.get(
            tenant_id=self.tenant,
            engagement_id=self.eng,
            target_system="LIBRARY",
        )

        category.access_policy_code = "PORTAL_ONLY"
        category.save(update_fields=["access_policy_code", "updated_at"])
        current = self.service.provision_engagement_access(
            tenant_id=self.tenant, engagement=self.eng
        )

        self.assertEqual({grant.target_system for grant in current}, {"EXTERNAL_PORTAL"})
        self.assertTrue(
            HrExternalProvisioningRequest.objects.filter(
                tenant_id=self.tenant,
                idempotency_key=f"revoke:{library.id}",
                operation="REVOKE",
                status=ProvisioningStatus.PENDING,
            ).exists()
        )
        self.assertEqual(
            HrExternalProvisioningRequest.objects.filter(
                tenant_id=self.tenant,
                engagement_id=self.eng,
                operation="GRANT",
                status=ProvisioningStatus.PENDING,
            ).count(),
            1,
        )

    def test_wrong_tenant_provisioning_is_fail_closed(self):
        with self.assertRaises(AccessScopeInvalid):
            self.service.provision_engagement_access(
                tenant_id=999,
                engagement=self.eng,
            )

        self.assertFalse(
            HrExternalAccessGrant.objects.filter(engagement_id=self.eng).exists()
        )

    def test_revoke_only_affects_own_grants(self):
        # 两个 engagement（不同 profile 同一 person 两个学院并行）—— 用第二个 profile
        from hr_staff.models import HrPerson

        person2 = HrPerson.objects.create(tenant_id=self.tenant, legal_name="吴工")
        profile2 = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=person2.id,
            primary_category_code="EXTERNAL_TEACHER",
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

        self.service.provision_engagement_access(tenant_id=self.tenant, engagement=self.eng)
        self.service.provision_engagement_access(tenant_id=self.tenant, engagement=eng2)

        revoked = self.service.revoke_engagement_access(tenant_id=self.tenant, engagement=self.eng)
        # 只撤销 eng 的 grants，eng2 的 grants 不动（§138.14/§99）
        self.assertEqual(len(revoked), 1)
        eng2_grants = HrExternalAccessGrant.objects.filter(engagement_id=eng2)
        self.assertEqual(eng2_grants.count(), 1)
        for g in eng2_grants:
            self.assertIn(g.status, [AccessGrantStatus.PENDING, AccessGrantStatus.GRANTED])

    def test_revocation_failure_raises_risk_not_revert(self):
        grants = self.service.provision_engagement_access(tenant_id=self.tenant, engagement=self.eng)
        # 模拟一个 grant 撤权失败
        for g in grants:
            g.status = AccessGrantStatus.REVOKE_FAILED
            g.save()
        self.service.raise_revocation_risk(
            tenant_id=self.tenant, engagement_id=self.eng.id, note="IAM timeout"
        )
        risk_event = HrExternalLifecycleEvent.objects.filter(
            event_type="ExternalAccessRevocationFailed"
        ).first()
        self.assertIsNotNone(risk_event)
        self.assertEqual(risk_event.payload_json.get("risk"), RiskSeverity.CRITICAL)
        # Engagement 保持原状态，不因撤权失败反转（§105）
        self.eng.refresh_from_db()
        self.assertEqual(self.eng.status, ExternalEngagementStatus.ACTIVE)


class ReconciliationTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="郑工")
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="EXTERNAL_EXPERT",
        )
        self.eng = EngagementService().create_engagement(
            EngagementCreateInput(
                tenant_id=self.tenant,
                person_id=self.person.id,
                profile_id=self.profile.id,
                category_id=self.profile.primary_category.id,
                host_organization_id=1,
                start_at=date(2026, 9, 1),
                end_at=date(2026, 12, 31),
            )
        )

    def test_academic_identity_drift_detected(self):
        HrExternalAcademicIdentity.objects.create(
            tenant_id=self.tenant,
            engagement_id=self.eng,
            external_teacher_no="EXT2026000001",
            academic_teacher_id="T20260001",
            valid_from=date(2026, 9, 1),
            valid_to=date(2026, 12, 31),
            status=AcademicIdentityStatus.ACTIVE,
        )
        self.eng.status = ExternalEngagementStatus.ENDED
        self.eng.save()
        report = ReconciliationService().reconcile_academic_identities(tenant_id=self.tenant)
        self.assertEqual(report.drift_count, 1)
        self.assertEqual(report.drift[0]["riskType"], "ACADEMIC_IDENTITY_DRIFT")

    def test_access_outlives_engagement_drift_detected(self):
        HrExternalAccessGrant.objects.create(
            tenant_id=self.tenant,
            engagement_id=self.eng,
            target_system="ACADEMIC",
            role_code="ACADEMIC_TEACHER",
            expires_at=timezone.now() + timedelta(days=5),
            status=AccessGrantStatus.GRANTED,
        )
        self.eng.status = ExternalEngagementStatus.ENDED
        self.eng.save()
        report = ReconciliationService().reconcile_access_grants(tenant_id=self.tenant)
        self.assertEqual(report.drift_count, 1)
        self.assertEqual(report.drift[0]["riskType"], "ACCESS_OUTLIVES_ENGAGEMENT")
