import json
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, TestCase

from hr_payroll import api
from hr_payroll.models import PayrollPeriod, PayrollResultFact
from hr_payroll.services.adjustment_service import PayrollAdjustmentError, PayrollAdjustmentService


class PayrollReversalAuthorityServiceTests(TestCase):
    @patch("hr_payroll.services.adjustment_service.PayrollPeriod.objects")
    @patch("hr_payroll.services.adjustment_service.PayrollResultFact.objects")
    def test_reversal_negates_linear_chain_and_seals_authority_metadata(self, result_objects, period_objects):
        root = MagicMock(
            id=uuid.uuid4(), status=PayrollResultFact.Status.FINALIZED,
            payroll_period_id=uuid.uuid4(), staff_id=uuid.uuid4(), currency_code="CNY",
            gross_amount=Decimal("1000"), deduction_amount=Decimal("100"), net_amount=Decimal("900"),
            supersedes_result_id=None,
        )
        source = MagicMock(
            id=uuid.uuid4(), status=PayrollResultFact.Status.ADJUSTED,
            payroll_period_id=root.payroll_period_id, staff_id=root.staff_id, currency_code="CNY",
            gross_amount=Decimal("100"), deduction_amount=Decimal("20"), net_amount=Decimal("80"),
            supersedes_result_id=root.id,
        )
        query = result_objects.select_for_update.return_value.filter.return_value
        query.first.side_effect = [source, root, None]
        query.exists.return_value = False
        period_objects.select_for_update.return_value.filter.return_value.first.return_value = MagicMock(
            status=PayrollPeriod.Status.FINALIZED
        )
        created = MagicMock()
        result_objects.create.return_value = created

        outcome = PayrollAdjustmentService(77, actor_user_id=9001).append_reversal(
            source_result_id=source.id, reversal_no="REV-1", reason="approved correction",
            evidence_ref="evidence://rev/1",
        )

        self.assertTrue(outcome.created)
        self.assertIs(outcome.reversal, created)
        result_objects.create.assert_called_once_with(
            tenant_id=77, result_no="REV-1", payroll_period_id=root.payroll_period_id,
            staff_id=root.staff_id, currency_code="CNY", gross_amount=Decimal("-1100"),
            deduction_amount=Decimal("-120"), net_amount=Decimal("-980"),
            status=PayrollResultFact.Status.REVERSED, supersedes_result_id=source.id,
            authority_reason="approved correction", authority_evidence_ref="evidence://rev/1",
            authority_actor_id=9001,
        )

    @patch("hr_payroll.services.adjustment_service.PayrollResultFact.objects")
    def test_reversal_requires_latest_non_reversed_source(self, result_objects):
        source = MagicMock(id=uuid.uuid4(), status=PayrollResultFact.Status.REVERSED)
        result_objects.select_for_update.return_value.filter.return_value.first.return_value = source
        with self.assertRaises(PayrollAdjustmentError) as cm:
            PayrollAdjustmentService(77).append_reversal(
                source_result_id=source.id, reversal_no="REV-2", reason="duplicate",
            )
        self.assertEqual(cm.exception.code, "PAYROLL_SOURCE_RESULT_NOT_FINAL")


class _User:
    is_authenticated = True
    is_superuser = True
    id = 9001


class PayrollReversalApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.source_id = uuid.uuid4()

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.PayrollAdjustmentService")
    def test_reversal_api_requires_reason_and_returns_sealed_result(self, service_cls, _tenant):
        fact = SimpleNamespace(
            id=uuid.uuid4(), result_no="REV-1", supersedes_result_id=self.source_id,
            payroll_period_id=uuid.uuid4(), staff_id=uuid.uuid4(), currency_code="CNY",
            gross_amount=Decimal("-1100"), deduction_amount=Decimal("-120"), net_amount=Decimal("-980"),
            status="REVERSED", authority_reason="approved correction",
            authority_evidence_ref="evidence://rev/1", authority_actor_id=9001,
        )
        service_cls.return_value.append_reversal.return_value = SimpleNamespace(reversal=fact, created=True)
        request = self.factory.post(
            "/api/v1/hr/payroll/results/x/reversal/",
            data=json.dumps({"reversalNo": "REV-1", "reason": "approved correction", "evidenceRef": "evidence://rev/1"}),
            content_type="application/json",
        )
        request.user = _User()
        response = api.reverse_result(request, self.source_id)
        self.assertEqual(response.status_code, 201)
        body = json.loads(response.content)
        self.assertEqual(body["schemaVersion"], "hr15.reversal.1")
        self.assertEqual(body["data"]["status"], "REVERSED")
        service_cls.assert_called_once_with(77, actor_user_id=9001)
        service_cls.return_value.append_reversal.assert_called_once_with(
            source_result_id=self.source_id, reversal_no="REV-1", reason="approved correction",
            evidence_ref="evidence://rev/1",
        )

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    def test_reversal_api_rejects_missing_reason(self, _tenant):
        request = self.factory.post(
            "/api/v1/hr/payroll/results/x/reversal/",
            data=json.dumps({"reversalNo": "REV-1"}), content_type="application/json",
        )
        request.user = _User()
        response = api.reverse_result(request, self.source_id)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["error"]["code"], "PAYROLL_REVERSAL_REASON_REQUIRED")
