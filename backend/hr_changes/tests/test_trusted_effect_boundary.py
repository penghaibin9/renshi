import inspect
import json
import uuid
from datetime import date
from types import SimpleNamespace

from django.test import RequestFactory, SimpleTestCase, TestCase

from hr_changes.constants import CaseStatus, ChangeActionCode
from hr_changes.context import HrChangeRequestContext, HrChangeScope
from hr_changes.models import (
    HrChangeApprovalSnapshot,
    HrChangeDownstreamEffect,
    HrChangeEffectiveSnapshot,
    HrChangeProposal,
    HrChangeTransition,
    HrPersonnelChangeCase,
)
from hr_changes.providers.effect import (
    EffectProviderError,
    EffectProviderRegistry,
    TrustedEffectReceipt,
)
from hr_changes.services.apply_service import ApplyService
from hr_changes.tests.factories import make_case


class TrustedReceiptContractTests(SimpleTestCase):
    def test_registry_missing_and_tampered_receipt_fail_closed(self):
        registry = EffectProviderRegistry()
        with self.assertRaises(EffectProviderError) as missing:
            registry.require(ChangeActionCode.ORG_TRANSFER)
        self.assertEqual(missing.exception.code, "CHANGE_EFFECT_PROVIDER_UNAVAILABLE")

        receipt = TrustedEffectReceipt.issue(
            provider_code="HR06_CANONICAL_HR02_HR03_V1",
            tenant_id=77,
            case_id="case-1",
            case_version=9,
            staff_id="staff-1",
            action_code=ChangeActionCode.ORG_TRANSFER,
            effective_at=date(2026, 8, 30),
            approval_snapshot_id="approval-1",
            approval_snapshot_hash="a" * 64,
            idempotency_key="apply-1",
            source_fact_ids=["source-1"],
            target_fact_ids=["target-1"],
            position_changes={},
            followup=[],
        )
        receipt.target_fact_ids.append("forged")
        with self.assertRaises(EffectProviderError) as tampered:
            receipt.verify(
                tenant_id=77,
                case_id="case-1",
                case_version=9,
                staff_id="staff-1",
                action_code=ChangeActionCode.ORG_TRANSFER,
                effective_at=date(2026, 8, 30),
                approval_snapshot_id="approval-1",
                approval_snapshot_hash="a" * 64,
                idempotency_key="apply-1",
            )
        self.assertEqual(tampered.exception.code, "CHANGE_EFFECT_RECEIPT_INVALID")

    def test_static_api_and_worker_contract_rejects_client_authority(self):
        from hr_changes.api import changes
        from hr_changes.jobs import apply_due_cases

        api_source = inspect.getsource(changes)
        job_source = inspect.getsource(apply_due_cases)
        self.assertIn("_ACTION_PERMISSIONS", api_source)
        self.assertIn("_FORBIDDEN_EFFECT_FIELDS", api_source)
        self.assertNotIn("date.today", job_source)
        self.assertIn("tenant_id", job_source)
        self.assertIn("as_of", job_source)
        with self.assertRaisesRegex(
            ValueError, "HR06_EFFECTIVE_REQUIRES_TRUSTED_EXECUTION_RECEIPT"
        ):
            HrPersonnelChangeCase.objects.none().update(status=CaseStatus.EFFECTIVE)

        migration = inspect.getsource(
            __import__(
                "hr_changes.migrations.0008_trusted_effect_provider_boundary",
                fromlist=["Migration"],
            )
        )
        for marker in (
            "hr06_case_no_fake_effective_insert",
            "hr06_case_trusted_effective_update",
            "HR06_TRUSTED_EXECUTION_RECEIPT_INVALID",
            "atomic = False",
        ):
            self.assertIn(marker, migration)

    def test_action_permission_is_dynamic_and_effect_payload_cannot_forge_authority(self):
        from unittest.mock import patch

        from hr_changes.api import changes

        factory = RequestFactory()
        case_id = uuid.uuid4()
        submit_only = SimpleNamespace(
            is_authenticated=True,
            is_superuser=False,
            id=12,
            has_perm=lambda code: code == "hr.change.submit",
        )
        approval = factory.post(
            f"/api/hr/v1/changes/{case_id}/approve",
            data="{}",
            content_type="application/json",
        )
        approval.user = submit_only
        context = HrChangeRequestContext(
            tenant_id=77,
            as_of=date(2026, 8, 30),
            scope=HrChangeScope(scope_type="SCHOOL"),
        )
        with patch("hr_changes.api.changes.make_hr_change_context", return_value=context):
            response = changes.change_action(approval, case_id, "approve")
        self.assertEqual(response.status_code, 403)

        superuser = SimpleNamespace(
            is_authenticated=True,
            is_superuser=True,
            id=1,
            has_perm=lambda _code: True,
        )
        forged = factory.post(
            f"/api/hr/v1/changes/{case_id}/apply",
            data=json.dumps(
                {
                    "status": "EFFECTIVE",
                    "providerReceipt": {"trusted": True},
                    "effectiveAt": "2026-08-30",
                }
            ),
            content_type="application/json",
        )
        forged.user = superuser
        with patch("hr_changes.api.changes.make_hr_change_context", return_value=context):
            response = changes.change_action(forged, case_id, "apply")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "CHANGE_INVALID_PAYLOAD",
        )


class TrustedEffectRollbackTests(TestCase):
    tenant_id = 606

    def _approved_case(self, *, approval_complete=True):
        case = make_case(
            self.tenant_id,
            action_code=ChangeActionCode.ORG_TRANSFER,
            requested_effective_at=date(2026, 8, 30),
            status=CaseStatus.APPROVED_WAITING_EFFECTIVE,
        )
        snapshot = HrChangeApprovalSnapshot.objects.create(
            change_case_id=case,
            workflow_version=1,
            steps_json=[{
                "step_no": 1,
                "status": "APPROVED" if approval_complete else "PENDING",
                "approved_by": 9001 if approval_complete else None,
            }],
        )
        case.approval_instance_id = str(snapshot.id)
        case.save(update_fields=["approval_instance_id", "updated_at"])
        from hr_changes.services.effect_intent import effect_intent_hash

        HrChangeTransition.objects.create(
            change_case_id=case,
            tenant_id=self.tenant_id,
            from_status=CaseStatus.UNDER_APPROVAL,
            to_status=CaseStatus.APPROVED_WAITING_EFFECTIVE,
            action="approve",
            actor_id=9001,
            snapshot_hash=effect_intent_hash(case, snapshot),
        )
        return case

    def test_provider_partial_write_is_rolled_back_before_apply_failed(self):
        case = self._approved_case()

        class PartialProvider:
            provider_code = "TEST_PARTIAL_PROVIDER"

            def execute(self, **kwargs):
                HrChangeDownstreamEffect.objects.create(
                    change_case_id=kwargs["case"],
                    tenant_id=self.tenant_id,
                    target_domain="HR99",
                    effect_type="SHOULD_ROLL_BACK",
                    status="PENDING",
                )
                raise EffectProviderError(
                    "CHANGE_EFFECT_PROVIDER_PARTIAL",
                    "provider stopped after a partial write",
                )

        provider = PartialProvider()
        provider.tenant_id = self.tenant_id
        registry = EffectProviderRegistry()
        registry.register([ChangeActionCode.ORG_TRANSFER], provider)

        result = ApplyService(
            self.tenant_id,
            actor_user_id=9001,
            provider_registry=registry,
        ).apply_case(
            case.id,
            as_of=date(2026, 8, 30),
            request_id="trusted-apply-1",
        )

        self.assertEqual(result.status, CaseStatus.APPLY_FAILED)
        self.assertFalse(
            HrChangeDownstreamEffect.objects.filter(
                change_case_id=case,
                effect_type="SHOULD_ROLL_BACK",
            ).exists()
        )
        self.assertFalse(HrChangeEffectiveSnapshot.objects.filter(change_case_id=case).exists())

    def test_unfrozen_approval_chain_cannot_enter_provider(self):
        case = self._approved_case(approval_complete=False)
        provider = SimpleNamespace(execute=lambda **_kwargs: self.fail("provider called"))
        registry = EffectProviderRegistry()
        registry.register([ChangeActionCode.ORG_TRANSFER], provider)

        result = ApplyService(
            self.tenant_id,
            provider_registry=registry,
        ).apply_case(case.id, as_of=date(2026, 8, 30), request_id="bad-approval")

        self.assertEqual(result.status, CaseStatus.APPLY_FAILED)
        self.assertFalse(HrChangeEffectiveSnapshot.objects.filter(change_case_id=case).exists())

    def test_approved_intent_tampering_cannot_enter_provider(self):
        case = self._approved_case()
        HrChangeProposal.objects.create(
            change_case_id=case,
            domain="assignment",
            field_code="organization",
            proposed_value_ref="forged-after-approval",
            effective_at=case.requested_effective_at,
        )
        provider = SimpleNamespace(execute=lambda **_kwargs: self.fail("provider called"))
        registry = EffectProviderRegistry()
        registry.register([ChangeActionCode.ORG_TRANSFER], provider)

        result = ApplyService(
            self.tenant_id,
            provider_registry=registry,
        ).apply_case(case.id, as_of=date(2026, 8, 30), request_id="tampered-intent")

        self.assertEqual(result.status, CaseStatus.APPLY_FAILED)
        self.assertFalse(HrChangeEffectiveSnapshot.objects.filter(change_case_id=case).exists())
