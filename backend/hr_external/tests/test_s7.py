"""S7 · 教学与服务任务契约测试。

覆盖（总册 §44-53）：
- 任务状态机（DRAFT→ASSIGNED→ACCEPTED→IN_PROGRESS→SUBMITTED→UNDER_REVIEW→COMPLETED/REJECTED）；
- Task Acceptance（§56）：拒绝不删除任务；
- 任务必须落在 Engagement 聘期内（§118）；
- 工作量：本人提交不自动成为正式数量（§52）；学院验证后才可结算；
- workload cap（§35/§121）；VERIFIED 后不可原地改（00 §20）；
- SettlementBasis：只输出 verified workload（§53/§138.9），不含金额。
"""

from datetime import date

from django.test import TestCase

from hr_external.constants import (
    ExternalEngagementStatus,
    ExternalTaskStatus,
    SettlementStatus,
    WorkloadVerificationStatus,
)
from hr_external.models import (
    HrExternalEngagement,
    HrExternalServiceTask,
    HrExternalSettlementBasis,
    HrExternalTaskEvidence,
    HrExternalWorkloadRecord,
)
from hr_payroll.models import ExternalSettlementBasisInput
from hr_external.services.category_service import CategoryService
from hr_external.services.engagement_service import EngagementService, EngagementCreateInput
from hr_external.services.profile_service import ProfileService
from hr_external.services.task_service import (
    TaskAlreadyFinalized,
    TaskOutsideEngagement,
    TaskService,
    WorkloadOverCap,
)


class TaskTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="陈老师")
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="PART_TIME_TEACHER",
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
                workload_cap=100,
            )
        )
        self.service = TaskService()

    def _task(self, start=date(2026, 9, 1), end=date(2027, 1, 31)):
        return self.service.create_task(
            tenant_id=self.tenant,
            engagement_id=self.eng.id,
            task_type="TEACHING",
            title="数据结构课程",
            planned_start=start,
            planned_end=end,
            owner_org_id=1,
            settlement_eligible=True,
        )

    def test_task_lifecycle(self):
        t = self._task()
        self.assertEqual(t.status, ExternalTaskStatus.DRAFT)
        t = self.service.assign(t, tenant_id=self.tenant)
        t = self.service.accept(t, action="ACCEPTED", tenant_id=self.tenant)
        self.assertEqual(t.status, ExternalTaskStatus.ACCEPTED)
        t = self.service.start(t, tenant_id=self.tenant)
        self.assertEqual(t.status, ExternalTaskStatus.IN_PROGRESS)
        t = self.service.submit(t, tenant_id=self.tenant)
        t = self.service.review(t, tenant_id=self.tenant)
        t = self.service.complete(t, tenant_id=self.tenant)
        self.assertEqual(t.status, ExternalTaskStatus.COMPLETED)

    def test_decline_keeps_task(self):
        t = self._task()
        self.service.assign(t, tenant_id=self.tenant)
        self.service.accept(
            t, action="DECLINE_WITH_REASON", reason="时间冲突", tenant_id=self.tenant
        )
        t.refresh_from_db()
        # 拒绝不直接删除任务（§56）
        self.assertIsNotNone(HrExternalServiceTask.objects.filter(id=t.id).first())
        self.assertEqual(t.acceptance, "DECLINED_WITH_REASON")

    def test_task_outside_engagement_blocked(self):
        with self.assertRaises(TaskOutsideEngagement):
            self._task(start=date(2028, 9, 1), end=date(2029, 1, 31))

    def test_workload_requires_verification(self):
        record = self.service.add_workload(
            tenant_id=self.tenant,
            engagement_id=self.eng.id,
            source="SYSTEM_CALCULATED",
            quantity=40,
            unit="学时",
            service_date=date(2026, 10, 15),
        )
        self.assertEqual(record.verification_status, WorkloadVerificationStatus.UNVERIFIED)
        self.assertEqual(record.settlement_status, SettlementStatus.NOT_ELIGIBLE)
        # 本人提交不自动成为正式数量（§52）
        self.service.verify_workload(
            record, tenant_id=self.tenant, verified=True, by=99
        )
        record.refresh_from_db()
        self.assertEqual(record.verification_status, WorkloadVerificationStatus.VERIFIED)
        self.assertEqual(record.settlement_status, SettlementStatus.PENDING)

    def test_workload_cap(self):
        self.service.add_workload(
            tenant_id=self.tenant,
            engagement_id=self.eng.id,
            source="ACADEMIC_VERIFIED",
            quantity=80,
            unit="学时",
            service_date=date(2026, 10, 1),
            verified=True,
        )
        with self.assertRaises(WorkloadOverCap):
            self.service.add_workload(
                tenant_id=self.tenant,
                engagement_id=self.eng.id,
                source="SYSTEM_CALCULATED",
                quantity=30,
                unit="学时",
                service_date=date(2026, 11, 1),
                verified=True,
            )

    def test_verified_workload_not_editable_inline(self):
        record = self.service.add_workload(
            tenant_id=self.tenant,
            engagement_id=self.eng.id,
            source="SYSTEM_CALCULATED",
            quantity=10,
            service_date=date(2026, 10, 1),
        )
        self.service.verify_workload(record, tenant_id=self.tenant, verified=True)
        with self.assertRaises(TaskAlreadyFinalized):
            self.service.verify_workload(
                record, tenant_id=self.tenant, verified=False
            )

    def test_settlement_basis_only_verified(self):
        rec1 = self.service.add_workload(
            tenant_id=self.tenant,
            engagement_id=self.eng.id,
            source="ACADEMIC_VERIFIED",
            quantity=60,
            unit="学时",
            service_date=date(2026, 10, 1),
        )
        self.service.verify_workload(rec1, tenant_id=self.tenant, verified=True)
        # 未验证的工作量
        self.service.add_workload(
            tenant_id=self.tenant,
            engagement_id=self.eng.id,
            source="SYSTEM_CALCULATED",
            quantity=999,
            unit="学时",
            service_date=date(2026, 10, 2),
        )
        basis = self.service.build_settlement_basis(
            tenant_id=self.tenant,
            engagement_id=self.eng.id,
            period="2026-10",
            policy_ref="EXT-POLICY-001",
        )
        self.assertEqual(basis.verified_workload, 60)  # 只聚合 verified
        self.assertEqual(basis.status, SettlementStatus.LOCKED)
        received = ExternalSettlementBasisInput.objects.get(
            tenant_id=self.tenant, source_engagement_id=self.eng.id, period_code="2026-10"
        )
        self.assertEqual(received.verified_workload, 60)
        self.assertNotIn("wage", basis.__dict__)  # HR08 不含金额

    def test_evidence_add(self):
        t = self._task()
        ev = self.service.add_evidence(
            tenant_id=self.tenant,
            task_id=t.id,
            evidence_type="TEACHING_EVALUATION",
            submitted_by=1,
        )
        self.assertIsInstance(ev, HrExternalTaskEvidence)
        self.assertEqual(ev.status, "UPLOADED")
