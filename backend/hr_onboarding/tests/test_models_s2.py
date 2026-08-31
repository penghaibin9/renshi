"""
hr_onboarding/tests/test_models_s2.py

HR05-S2 权威模型测试：
- 所有权威表带 tenant_id（A0 fail-closed DB 层）；
- source_type+source_id 唯一（HR04 HANDOFF 幂等 DB 兜底）；
- case_no tenant 唯一；报到 checkin 幂等唯一；task instance case+definition+cycle 唯一；
- portal access token_hash 唯一 + 状态默认 ACTIVE；activation snapshot 每 case 一份；
- 状态机默认值（case=CREATED, task=NOT_STARTED, provisioning=PENDING）。
"""

from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Field
from django.test import TestCase

from hr_onboarding.models import (
    HrActivationAttempt,
    HrOnboardingActivationSnapshot,
    HrOnboardingAuthorityMode,
    HrOnboardingCase,
    HrOnboardingMaterialRequirement,
    HrOnboardingOutboxEvent,
    HrOnboardingStageDefinition,
    HrOnboardingTaskDefinition,
    HrOnboardingTaskInstance,
    HrOnboardingTemplate,
    HrOnboardingTemplateVersion,
    HrPrehirePortalAccess,
    HrProbationCase,
    HrProvisioningRequest,
    HrReportCheckin,
)

ALL_AUTHORITY_MODELS = [
    HrOnboardingTemplate,
    HrOnboardingTemplateVersion,
    HrOnboardingStageDefinition,
    HrOnboardingTaskDefinition,
    HrOnboardingCase,
    HrOnboardingMaterialRequirement,
    HrOnboardingTaskInstance,
    HrProvisioningRequest,
    HrProbationCase,
    HrReportCheckin,
    HrPrehirePortalAccess,
    HrActivationAttempt,
    HrOnboardingActivationSnapshot,
    HrOnboardingOutboxEvent,
    HrOnboardingAuthorityMode,
]


def _build_template(tenant_id=1):
    tpl = HrOnboardingTemplate.objects.create(tenant_id=tenant_id, code="T-TEACHER", name="教师入职模板")
    ver = HrOnboardingTemplateVersion.objects.create(
        tenant_id=tenant_id, template=tpl, version_no=1, status="ACTIVE"
    )
    HrOnboardingStageDefinition.objects.create(
        tenant_id=tenant_id, template_version=ver, code="PRE", title="报到前准备", sequence=1
    )
    task_def = HrOnboardingTaskDefinition.objects.create(
        tenant_id=tenant_id,
        template_version=ver,
        code="IT-EMAIL",
        title="开通邮箱",
        responsible_role="IT_SERVICE",
        blocking_level="BLOCKS_ACTIVATION",
        automation_handler="CREATE_EMAIL",
    )
    HrOnboardingMaterialRequirement.objects.create(
        tenant_id=tenant_id,
        template_version=ver,
        material_type="ID_CARD",
        label="身份证",
        blocking_phase="ACTIVATION",
        reuse_policy="REVERIFY",
    )
    return tpl, ver, task_def


def _build_case(tenant_id=1, case_no="CASE-001", source_id="ph-001", **kwargs):
    return HrOnboardingCase.objects.create(
        tenant_id=tenant_id,
        case_no=case_no,
        source_type="HR04_HIRE",
        source_id=source_id,
        **kwargs,
    )


class TenantColumnTests(TestCase):
    def test_all_authority_models_have_tenant_id(self):
        for model in ALL_AUTHORITY_MODELS:
            field = model._meta.get_field("tenant_id")
            self.assertIsInstance(field, Field)
            self.assertTrue(field.db_index, f"{model.__name__}.tenant_id 应建索引")


class CaseConstraintsTests(TestCase):
    def test_source_type_source_id_unique(self):
        """HR04 HANDOFF 重复消费的 DB 兜底：同 tenant+source 不重复。"""
        _build_case()
        with self.assertRaises(IntegrityError), transaction.atomic():
            _build_case(case_no="CASE-002")

    def test_case_no_tenant_unique(self):
        _build_case(source_id="ph-001")
        # 不同 tenant 允许同 case_no
        _build_case(tenant_id=2, case_no="CASE-001", source_id="ph-002")
        # 同 tenant 同 case_no 拒绝
        with self.assertRaises(IntegrityError), transaction.atomic():
            _build_case(case_no="CASE-001", source_id="ph-003")

    def test_default_status_created(self):
        case = _build_case()
        self.assertEqual(case.status, "CREATED")
        self.assertEqual(case.activation_status, "NOT_STARTED")
        self.assertEqual(case.person_match_status, "NO_MATCH")


class ReportCheckinIdempotencyTests(TestCase):
    def test_report_checkin_unique_per_case_at(self):
        case = _build_case()
        from datetime import datetime, timezone

        at = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
        HrReportCheckin.objects.create(
            tenant_id=1, case=case, actual_report_at=at, checked_identity=True, operator_id=1
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            HrReportCheckin.objects.create(
                tenant_id=1, case=case, actual_report_at=at, checked_identity=True, operator_id=2
            )


class TaskInstanceConstraintTests(TestCase):
    def test_task_instance_unique_case_definition_cycle(self):
        _, _, task_def = _build_template()
        case = _build_case()
        HrOnboardingTaskInstance.objects.create(
            tenant_id=1, case=case, definition=task_def, assignee_type="IT_SERVICE"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            HrOnboardingTaskInstance.objects.create(
                tenant_id=1, case=case, definition=task_def, assignee_type="IT_SERVICE"
            )

    def test_task_default_status(self):
        _, _, task_def = _build_template()
        case = _build_case()
        inst = HrOnboardingTaskInstance.objects.create(tenant_id=1, case=case, definition=task_def)
        self.assertEqual(inst.status, "NOT_STARTED")
        self.assertEqual(inst.cycle, "INITIAL")


class PortalAccessTokenTests(TestCase):
    def test_token_hash_unique_and_default_active(self):
        case = _build_case()
        from datetime import datetime, timezone

        expires = datetime(2026, 10, 1, tzinfo=timezone.utc)
        HrPrehirePortalAccess.objects.create(
            tenant_id=1, case=case, token_hash="abc123", expires_at=expires
        )
        case2 = _build_case(case_no="CASE-002", source_id="ph-002")
        with self.assertRaises(IntegrityError), transaction.atomic():
            HrPrehirePortalAccess.objects.create(
                tenant_id=1, case=case2, token_hash="abc123", expires_at=expires
            )

        portal = HrPrehirePortalAccess.objects.get(token_hash="abc123")
        self.assertEqual(portal.status, "ACTIVE")
        self.assertEqual(portal.failed_attempts, 0)


class ProvisioningAndActivationTests(TestCase):
    def test_provisioning_default_pending(self):
        case = _build_case()
        req = HrProvisioningRequest.objects.create(
            tenant_id=1, case=case, target_system="IAM", operation="CREATE_SSO", idempotency_key="p-1"
        )
        self.assertEqual(req.status, "PENDING")
        self.assertEqual(req.attempt_count, 0)

    def test_activation_attempt_idempotency_unique(self):
        case = _build_case()
        HrActivationAttempt.objects.create(
            tenant_id=1, case=case, idempotency_key="activate-1", status="SUCCEEDED"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            HrActivationAttempt.objects.create(
                tenant_id=1, case=case, idempotency_key="activate-1", status="IN_PROGRESS"
            )

    def test_activation_snapshot_one_per_case(self):
        case = _build_case()
        HrOnboardingActivationSnapshot.objects.create(
            tenant_id=1,
            case=case,
            person_id=None,
            staff_no="T000001",
            source_versions_json={"hr04": "v1"},
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            HrOnboardingActivationSnapshot.objects.create(
                tenant_id=1, case=case, staff_no="T000002"
            )


class ProbationModelTests(TestCase):
    def test_probation_defaults(self):
        case = _build_case()
        start = date(2026, 9, 1)
        pc = HrProbationCase.objects.create(
            tenant_id=1,
            onboarding_case=case,
            start_date=start,
            planned_end_date=start + timedelta(days=180),
        )
        self.assertEqual(pc.status, "NOT_STARTED")
        self.assertEqual(pc.result, "NONE")
        self.assertEqual(pc.extension_count, 0)
