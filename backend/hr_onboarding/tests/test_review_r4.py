"""
hr_onboarding/tests/test_review_r4.py

HR05 第四轮深入复审新增测试：
- Activation Gate：模板存在但材料未实例化 → 阻断（R4-1 回归）；
- Probation REVIEW_DUE 可直接 CONFIRMED/FAILED（R4-2 回归）；
- probation open 要求 case ACTIVE（R4-5 回归）；
- outbox dispatcher 幂等投递（R4-5 回归）。
"""

from datetime import date, timedelta
from uuid import uuid4

from django.test import TestCase

from hr_onboarding.api.exceptions import Hr05ApiError
from hr_onboarding.constants import MaterialBlockingPhase, ProbationStatus
from hr_onboarding.jobs.outbox_dispatcher import (
    DispatchResult,
    OutboxHandlerRegistry,
    dispatch_pending,
)
from hr_onboarding.models import (
    HrOnboardingCase,
    HrOnboardingMaterialRequirement,
    HrOnboardingOutboxEvent,
    HrProbationCase,
)
from hr_onboarding.policies.activation_policy import evaluate_activation_gate
from hr_onboarding.services.case_service import CaseService
from hr_onboarding.services.outbox_service import enqueue_outbox
from hr_onboarding.services.probation_service import ProbationService

from .test_s3 import _handoff_request
from .test_models_s2 import _build_template

TODAY = date(2026, 9, 1)


def _active_case():
    """构造 ACTIVE 状态 case（含模板版本）。"""
    import uuid as _uuid

    _, version, _ = _build_template(tenant_id=1)
    service = CaseService(tenant_id=1)
    r = service.create_case_from_handoff(
        _handoff_request(idem_key=f"k-r4-handoff-{_uuid.uuid4().hex}"),
        idempotency_key=f"k-r4-case-{_uuid.uuid4().hex}",
    )
    case = HrOnboardingCase.objects.get(id=r["case_id"])
    case.template_version_id = version.id
    case.status = "ACTIVE"
    case.save(update_fields=["template_version_id", "status"])
    return case


class ActivationGateMaterialTests(TestCase):
    def test_gate_blocks_when_activation_material_not_instantiated(self):
        """R4-1：模板存在但 ACTIVATION 阻断材料未实例化 → Gate 拒绝（不得放行）。"""
        case = _active_case()
        # 模板已含 material requirement（blocking_phase 默认 ACTIVATION），但未 ensure → 无 material 行
        gate = evaluate_activation_gate(tenant_id=1, case=case, effective_at=TODAY)
        self.assertFalse(gate.passed)
        codes = [i.code for i in gate.items if not i.ok]
        self.assertIn("BLOCKING_MATERIALS_OK", codes)

    def test_gate_passes_when_material_verified(self):
        """材料已核验 → Gate 材料子项通过（不断言整体，其他项由各自测试覆盖）。"""
        case = _active_case()
        from hr_onboarding.constants import MaterialStatus
        from hr_onboarding.models import HrOnboardingMaterial
        from hr_onboarding.services.material_service import ensure_materials_from_requirements

        ensure_materials_from_requirements(case)
        material = HrOnboardingMaterial.objects.filter(case=case).first()
        material.status = MaterialStatus.VERIFIED
        material.save(update_fields=["status"])

        gate = evaluate_activation_gate(tenant_id=1, case=case, effective_at=TODAY)
        item = [i for i in gate.items if i.code == "BLOCKING_MATERIALS_OK"][0]
        self.assertTrue(item.ok)

    def test_gate_material_block_when_missing(self):
        """材料存在但状态 MISSING → 材料子项拒绝。"""
        case = _active_case()
        from hr_onboarding.services.material_service import ensure_materials_from_requirements

        ensure_materials_from_requirements(case)  # 状态默认 MISSING
        gate = evaluate_activation_gate(tenant_id=1, case=case, effective_at=TODAY)
        item = [i for i in gate.items if i.code == "BLOCKING_MATERIALS_OK"][0]
        self.assertFalse(item.ok)


class ProbationReviewDueTests(TestCase):
    def test_review_due_can_confirm(self):
        """R4-2：REVIEW_DUE → CONFIRMED 合法（到期直接转正）。"""
        case = _active_case()
        service = ProbationService(tenant_id=1, actor_user_id=9)
        probation = service.open_probation(
            case,
            staff_master_id=uuid4(),
            employment_relationship_id=uuid4(),
            start_date=TODAY,
            planned_end_date=TODAY + timedelta(days=180),
        )
        probation.status = ProbationStatus.REVIEW_DUE
        probation.save(update_fields=["status"])
        confirmed = service.confirm(probation, decision_reason="到期合格", as_of=TODAY)
        self.assertEqual(confirmed.status, ProbationStatus.CONFIRMED)

    def test_review_due_can_fail(self):
        """R4-2：REVIEW_DUE → FAILED 合法（到期判不通过）。"""
        case = _active_case()
        service = ProbationService(tenant_id=1, actor_user_id=9)
        probation = service.open_probation(
            case,
            staff_master_id=uuid4(),
            employment_relationship_id=uuid4(),
            start_date=TODAY,
            planned_end_date=TODAY + timedelta(days=180),
        )
        probation.status = ProbationStatus.REVIEW_DUE
        probation.save(update_fields=["status"])
        failed = service.fail(probation, reason="到期不合格")
        self.assertEqual(failed.status, ProbationStatus.FAILED)

    def test_open_requires_active_case(self):
        """R4-5：CREATED case 不可开启试用。"""
        import uuid as _uuid

        service = CaseService(tenant_id=1)
        r = service.create_case_from_handoff(
            _handoff_request(idem_key=f"k-r4b-handoff-{_uuid.uuid4().hex}"),
            idempotency_key=f"k-r4b-case-{_uuid.uuid4().hex}",
        )
        case = HrOnboardingCase.objects.get(id=r["case_id"])  # CREATED
        with self.assertRaises(Hr05ApiError):
            ProbationService(tenant_id=1).open_probation(
                case,
                staff_master_id=uuid4(),
                employment_relationship_id=uuid4(),
                start_date=TODAY,
                planned_end_date=TODAY + timedelta(days=180),
            )


class OutboxDispatcherTests(TestCase):
    def test_dispatch_pending_marks_sent(self):
        """R4-5：只有已注册 handler 的明确外部回执才置 SENT。"""
        case = _active_case()
        event = enqueue_outbox(
            tenant_id=1,
            event_type="StaffActivated",
            aggregate_type="HrOnboardingCase",
            aggregate_id=str(case.id),
        )
        registry = OutboxHandlerRegistry()
        registry.register(
            "StaffActivated",
            lambda envelope: DispatchResult.ack(f"test:{envelope.event_id}"),
        )
        result = dispatch_pending(tenant_id=1, registry=registry)
        self.assertEqual(result["dispatched"], 1)
        event.refresh_from_db()
        self.assertEqual(event.status, HrOnboardingOutboxEvent.Status.SENT)
        self.assertEqual(event.attempts, 1)
        self.assertEqual(event.external_ref, f"test:{event.event_id}")


class ApiMethodDecoratorTests(TestCase):
    """R5-1：POST 动作不得误用 @require_GET（否则运行时 405）。"""

    def test_confirm_intent_accepts_post(self):
        from unittest import mock

        from django.contrib.auth import get_user_model
        from django.test import RequestFactory

        from hr_onboarding.api import views as api_views

        User = get_user_model()
        user = User.objects.create_user(username="r5admin", password="x", is_superuser=True)
        service = CaseService(tenant_id=1)
        r = service.create_case_from_handoff(
            _handoff_request(idem_key=f"k-r5-handoff-{uuid4().hex}"),
            idempotency_key=f"k-r5-case-{uuid4().hex}",
        )
        case = HrOnboardingCase.objects.get(id=r["case_id"])  # CREATED → PREPARING 合法

        request = RequestFactory().post(f"/api/hr/v1/onboarding/cases/{case.id}/confirm-intent")
        request.user = user
        # 注入 tenant context（selected_company）→ 通过 make_hr05_context
        with mock.patch(
            "hr_onboarding.api.base.resolve_tenant_from_request", return_value=1
        ):
            resp = api_views.hr05_case_confirm_intent(request, case_id=str(case.id))
        self.assertEqual(resp.status_code, 200)
        import json

        payload = json.loads(resp.content)
        self.assertEqual(payload["data"]["status"], "PREPARING")
