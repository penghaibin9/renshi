"""S9 · CorrectionService 状态机测试：全流程、RETURN≠REJECT、BP 字段防绕过、应用失败可追踪。"""

from django.test import TestCase

from hr_staff.constants import CorrectionEditMode, CorrectionStatus
from hr_staff.models import HrCorrectionCase, HrFieldGovernancePolicy
from hr_staff.services.correction_service import (
    CorrectionPolicyDenied,
    CorrectionService,
    CorrectionStateError,
)
from hr_staff.tests.factories import make_person, make_staff

TENANT = 1


def seed_policy(tenant_id=TENANT):
    HrFieldGovernancePolicy.objects.update_or_create(
        tenant_id=tenant_id,
        field_code="contact.work_email",
        defaults={
            "edit_mode": CorrectionEditMode.HR_DIRECT,
            "sensitivity_level": "RESTRICTED_HR",
            "required_evidence": True,
        },
    )
    HrFieldGovernancePolicy.objects.update_or_create(
        tenant_id=tenant_id,
        field_code="employment.effective_from",
        defaults={"edit_mode": CorrectionEditMode.BUSINESS_PROCESS_ONLY},
    )
    HrFieldGovernancePolicy.objects.update_or_create(
        tenant_id=tenant_id,
        field_code="identity.document_number",
        defaults={
            "edit_mode": CorrectionEditMode.HR_APPROVAL,
            "required_evidence": True,
            "approval_policy": "HR_DIRECTOR_APPROVAL",
        },
    )


class CorrectionFlowTests(TestCase):
    def setUp(self):
        seed_policy()
        self.staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T001238")
        self.svc = CorrectionService(TENANT, actor_user_id=1)

    def _create(self, field_code="contact.work_email", evidence=True):
        return self.svc.create_case(
            staff_id=self.staff,
            reason="邮箱纠错",
            items=[
                {
                    "field_code": field_code,
                    "fact_type": "contact",
                    "old_value_masked": "a@x.com",
                    "new_value_masked": "b@x.com",
                }
            ],
            evidence_material_id="00000000-0000-0000-0000-000000000001" if evidence else None,
        )

    def test_full_happy_flow(self):
        case = self._create()
        self.assertEqual(case.status, CorrectionStatus.DRAFT)
        self.svc.submit(case.id)
        self.svc.review(case.id)
        self.svc.approve(case.id)
        self.svc.apply(case.id, apply_fn=lambda c: None)
        case.refresh_from_db()
        self.assertEqual(case.status, CorrectionStatus.APPLIED)
        self.assertFalse(case.apply_error)
        for item in case.items.all():
            self.assertTrue(item.applied)

    def test_return_not_reject(self):
        case = self._create()
        self.svc.submit(case.id)
        self.svc.review(case.id)
        self.svc.return_(case.id, "证据不清晰")
        case.refresh_from_db()
        self.assertEqual(case.status, CorrectionStatus.RETURNED)
        self.assertEqual(case.return_reason, "证据不清晰")
        # RETURNED 可 resubmit
        self.svc.resubmit(case.id)
        case.refresh_from_db()
        self.assertEqual(case.status, CorrectionStatus.RESUBMITTED)

    def test_business_process_only_field_rejected(self):
        """#55 负向：更正流程不能改 BUSINESS_PROCESS_ONLY 字段。"""
        with self.assertRaises(CorrectionPolicyDenied) as ctx:
            self._create(field_code="employment.effective_from")
        self.assertIn("正式业务流程", str(ctx.exception))

    def test_required_evidence_missing_rejected(self):
        with self.assertRaises(CorrectionPolicyDenied) as ctx:
            self._create(evidence=False)
        self.assertEqual(ctx.exception.code, "CORRECTION_POLICY_DENIED")

    def test_approve_then_apply_failure_tracked(self):
        """审批成功后应用失败必须 FAILED + apply_error 可追踪，不得显示 success。
        P1-3：identity.document_number 是内置应用器拒绝的高敏字段。"""
        case = self._create(field_code="identity.document_number")
        self.svc.submit(case.id)
        self.svc.review(case.id)
        self.svc.approve(case.id, approve_high_risk=True)
        with self.assertRaises(CorrectionStateError):
            self.svc.apply(case.id)  # 内置应用器拒高敏 → FAILED
        case.refresh_from_db()
        self.assertEqual(case.status, CorrectionStatus.FAILED)
        self.assertIn("identity.document_number", case.apply_error)

    def test_apply_real_field_writes_authority(self):
        """P1-3：可应用字段（contact.work_email）经 apply 真实写入 PersonContact。"""
        from hr_staff.models import HrPersonContact

        case = self._create()  # contact.work_email
        self.svc.submit(case.id)
        self.svc.review(case.id)
        self.svc.approve(case.id)
        self.svc.apply(case.id)
        case.refresh_from_db()
        self.assertEqual(case.status, CorrectionStatus.APPLIED)
        contact = HrPersonContact.objects.filter(
            tenant_id=TENANT,
            person_id=self.staff.person_id,
            contact_kind="WORK_EMAIL",
        ).first()
        self.assertIsNotNone(contact)
        self.assertEqual(contact.contact_value, "b@x.com")
        self.assertTrue(all(i.applied for i in case.items.all()))

    def test_high_risk_retroactive_requires_director_approval(self):
        case = self.svc.create_case(
            staff_id=self.staff,
            reason="证件纠错",
            items=[
                {
                    "field_code": "identity.document_number",
                    "fact_type": "identity",
                    "old_value_masked": "110101****0011",
                    "new_value_masked": "110101****0022",
                }
            ],
            evidence_material_id="00000000-0000-0000-0000-000000000002",
        )
        self.svc.submit(case.id)
        self.svc.review(case.id)
        with self.assertRaises(CorrectionPolicyDenied):
            self.svc.approve(case.id, approve_high_risk=False)
        # 授权后可批准
        self.svc.approve(case.id, approve_high_risk=True)
        case.refresh_from_db()
        self.assertEqual(case.status, CorrectionStatus.APPROVED)

    def test_invalid_transition_rejected(self):
        case = self._create()
        with self.assertRaises(CorrectionStateError):
            self.svc.approve(case.id)  # DRAFT 不可直接 approve
