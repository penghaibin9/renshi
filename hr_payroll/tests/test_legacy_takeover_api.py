import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse
from django.utils import timezone

from hr_payroll import api


class SuperuserStub:
    id = 9
    is_authenticated = True
    is_superuser = True


class LegacyPayrollTakeoverApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    def _inventory():
        return SimpleNamespace(
            id=uuid.uuid4(),
            inventory_no="CUTOVER-1",
            status="COMPLETE",
            legacy_row_count=3,
            matched_row_count=3,
            unavailable_row_count=0,
            snapshot_hash="a" * 64,
            reason_codes_json=[],
            captured_at=timezone.now(),
        )

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_payroll.api.LegacyPayrollTakeoverService")
    def test_inventory_capture_uses_manage_boundary_and_idempotency_receipt(
        self, service_cls, _tenant
    ):
        inventory = self._inventory()
        service_cls.return_value.capture_inventory.return_value = SimpleNamespace(
            inventory=inventory, created=True
        )
        request = self.factory.post(
            "/api/v1/hr/payroll/legacy-takeover/inventories/",
            data=json.dumps({"inventoryNo": "CUTOVER-1"}),
            content_type="application/json",
        )
        request.user = SuperuserStub()

        response = api.legacy_takeover_inventories(request)

        self.assertEqual(response.status_code, 201)
        service_cls.assert_called_once_with(7, actor_user_id=9, correlation_id="")
        service_cls.return_value.capture_inventory.assert_called_once_with(
            inventory_no="CUTOVER-1"
        )
        self.assertIn(b'"status": "COMPLETE"', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_payroll.api.LegacyPayrollTakeoverService")
    def test_activation_forwards_only_explicit_cutover_request(self, service_cls, _tenant):
        inventory_id = uuid.uuid4()
        control = SimpleNamespace(
            id=uuid.uuid4(),
            status="ACTIVE",
            latest_inventory_id=inventory_id,
            latest_snapshot_hash="a" * 64,
            write_block_enabled=True,
            activation_evidence_hash="b" * 64,
            activation_evidence_json={"approvalTicket": "CAB-9", "rollbackPlanRef": "RB-9"},
            verified_at=timezone.now(),
            activated_at=timezone.now(),
        )
        service_cls.return_value.activate.return_value = control
        payload = {
            "inventoryId": str(inventory_id),
            "activationKey": "ACT-9",
            "evidence": {"approvalTicket": "CAB-9", "rollbackPlanRef": "RB-9"},
        }
        request = self.factory.post(
            "/api/v1/hr/payroll/legacy-takeover/activate/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        request.user = SuperuserStub()

        response = api.activate_legacy_takeover(request)

        self.assertEqual(response.status_code, 200)
        service_cls.return_value.activate.assert_called_once_with(
            inventory_id=str(inventory_id),
            activation_key="ACT-9",
            evidence=payload["evidence"],
        )
        self.assertIn(b'"writeBlockEnabled": true', response.content)
        self.assertIn(b'"schemaVersion": "hr15.legacy-takeover.1"', response.content)

    def test_inventory_endpoint_rejects_unsupported_method(self):
        request = self.factory.delete(
            "/api/v1/hr/payroll/legacy-takeover/inventories/"
        )
        request.user = SuperuserStub()

        response = api.legacy_takeover_inventories(request)

        self.assertEqual(response.status_code, 405)

    def test_takeover_routes_are_canonical(self):
        expected = {
            "hr_payroll_api:legacy-takeover-inventories": (
                "/api/v1/hr/payroll/legacy-takeover/inventories/"
            ),
            "hr_payroll_api:legacy-takeover-activate": (
                "/api/v1/hr/payroll/legacy-takeover/activate/"
            ),
            "hr_payroll_api:legacy-takeover-write-block-audits": (
                "/api/v1/hr/payroll/legacy-takeover/write-block-audits/"
            ),
        }
        for name, path in expected.items():
            self.assertEqual(reverse(name), path)
            self.assertEqual(resolve(path).view_name, name)
