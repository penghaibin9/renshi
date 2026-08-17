import json
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_payroll import api
from hr_payroll.services.adjustment_service import PayrollAdjustmentError


class _User:
    is_authenticated = True
    is_superuser = False

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, permission):
        return permission in self.permissions


class PayrollAdjustmentApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.source_id = uuid.UUID("00000000-0000-0000-0000-000000000101")
        self.payload = {
            "adjustmentNo": "ADJ-2026-08-001",
            "grossDelta": "100.00",
            "deductionDelta": "20.00",
            "netDelta": "80.00",
        }

    def _request(self, *, user, body=None, method="post"):
        builder = getattr(self.factory, method)
        request = builder(
            "/api/v1/hr/payroll/results/x/adjustments/",
            data=json.dumps(self.payload if body is None else body),
            content_type="application/json",
        )
        request.user = user
        return request

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value=[77])
    def test_read_only_user_cannot_adjust_payroll(self, _allowed, _tenant):
        request = self._request(user=_User({api.READ_PERMISSION}))

        with patch("hr_payroll.api.PayrollAdjustmentService") as service:
            response = api.adjust_result(request, self.source_id)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)["error"]["code"], "PERMISSION_DENIED")
        service.assert_not_called()

    def test_non_post_method_is_rejected_before_service(self):
        request = self.factory.get("/api/v1/hr/payroll/results/x/adjustments/")
        request.user = _User({api.ADJUST_PERMISSION})

        with patch("hr_payroll.api.PayrollAdjustmentService") as service:
            response = api.adjust_result(request, self.source_id)

        self.assertEqual(response.status_code, 405)
        service.assert_not_called()

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value=[77])
    def test_invalid_json_is_a_400_contract_error(self, _allowed, _tenant):
        request = self.factory.post(
            "/api/v1/hr/payroll/results/x/adjustments/",
            data=b"{broken-json",
            content_type="application/json",
        )
        request.user = _User({api.ADJUST_PERMISSION})

        response = api.adjust_result(request, self.source_id)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["error"]["code"], "INVALID_JSON")

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value=[77])
    @patch("hr_payroll.api.PayrollAdjustmentService")
    def test_writer_creates_adjustment_with_canonical_response(
        self, service_cls, _allowed, _tenant
    ):
        fact_id = uuid.UUID("00000000-0000-0000-0000-000000000401")
        period_id = uuid.UUID("00000000-0000-0000-0000-000000000201")
        staff_id = uuid.UUID("00000000-0000-0000-0000-000000000301")
        fact = SimpleNamespace(
            id=fact_id,
            result_no="ADJ-2026-08-001",
            supersedes_result_id=self.source_id,
            payroll_period_id=period_id,
            staff_id=staff_id,
            currency_code="CNY",
            gross_amount=Decimal("100.00"),
            deduction_amount=Decimal("20.00"),
            net_amount=Decimal("80.00"),
            status="ADJUSTED",
        )
        service_cls.return_value.append_adjustment.return_value = SimpleNamespace(
            adjustment=fact,
            created=True,
        )
        request = self._request(user=_User({api.ADJUST_PERMISSION}))

        response = api.adjust_result(request, self.source_id)
        body = json.loads(response.content)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(body["schemaVersion"], "hr15.adjustment.1")
        self.assertEqual(body["data"]["sourceResultId"], str(self.source_id))
        self.assertEqual(body["data"]["netDelta"], "80.00")
        service_cls.assert_called_once_with(77)
        service_cls.return_value.append_adjustment.assert_called_once_with(
            source_result_id=self.source_id,
            adjustment_no="ADJ-2026-08-001",
            gross_delta="100.00",
            deduction_delta="20.00",
            net_delta="80.00",
            currency_code=None,
        )

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value=[77])
    @patch("hr_payroll.api.PayrollAdjustmentService")
    def test_idempotent_existing_adjustment_returns_200(
        self, service_cls, _allowed, _tenant
    ):
        fact = SimpleNamespace(
            id=uuid.uuid4(),
            result_no="ADJ-2026-08-001",
            supersedes_result_id=self.source_id,
            payroll_period_id=uuid.uuid4(),
            staff_id=uuid.uuid4(),
            currency_code="CNY",
            gross_amount=Decimal("100.00"),
            deduction_amount=Decimal("20.00"),
            net_amount=Decimal("80.00"),
            status="ADJUSTED",
        )
        service_cls.return_value.append_adjustment.return_value = SimpleNamespace(
            adjustment=fact,
            created=False,
        )
        request = self._request(user=_User({api.ADJUST_PERMISSION}))

        response = api.adjust_result(request, self.source_id)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(json.loads(response.content)["data"]["created"])

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value=[77])
    @patch("hr_payroll.api.PayrollAdjustmentService")
    def test_source_not_found_maps_to_404(self, service_cls, _allowed, _tenant):
        service_cls.return_value.append_adjustment.side_effect = PayrollAdjustmentError(
            "PAYROLL_SOURCE_RESULT_NOT_FOUND", "source payroll result not found"
        )
        request = self._request(user=_User({api.ADJUST_PERMISSION}))

        response = api.adjust_result(request, self.source_id)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "PAYROLL_SOURCE_RESULT_NOT_FOUND",
        )

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value=[77])
    @patch("hr_payroll.api.PayrollAdjustmentService")
    def test_final_state_conflict_maps_to_409(self, service_cls, _allowed, _tenant):
        service_cls.return_value.append_adjustment.side_effect = PayrollAdjustmentError(
            "PAYROLL_SOURCE_RESULT_NOT_FINAL", "source result is not final"
        )
        request = self._request(user=_User({api.ADJUST_PERMISSION}))

        response = api.adjust_result(request, self.source_id)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "PAYROLL_SOURCE_RESULT_NOT_FINAL",
        )
