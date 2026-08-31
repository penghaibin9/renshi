from unittest.mock import patch
from types import SimpleNamespace
import json
import uuid

from django.test import RequestFactory, SimpleTestCase

from hr_data import legacy_api


class SuperuserStub:
    is_authenticated = True
    is_superuser = True


class Hr18LegacyReportAssetApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("hr_data.legacy_api.resolve_request_tenant", return_value=7)
    @patch("hr_data.legacy_api.LegacyReportAssetInventoryService")
    def test_endpoint_is_get_only_tenant_scoped_and_non_authoritative(
        self, service_cls, _tenant
    ):
        service_cls.return_value.snapshot.return_value = {
            "status": "COMPLETE",
            "authority": "HR18",
            "legacySource": "report.ReportTemplate",
            "legacyAuthority": False,
            "mappingPolicy": "NO_FORMAL_AUTHORITY_EQUIVALENT",
            "items": [],
        }
        request = self.factory.get("/api/v1/hr/data/legacy/report-assets/?limit=33")
        request.user = SuperuserStub()

        response = legacy_api.legacy_report_assets(request)

        self.assertEqual(response.status_code, 200)
        service_cls.assert_called_once_with(7)
        service_cls.return_value.snapshot.assert_called_once_with(limit=33)
        self.assertIn(b'"legacyAuthority": false', response.content)
        self.assertIn(b'"schemaVersion": "hr18.legacy-report-assets.1"', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_data.legacy_api.resolve_request_tenant", return_value=7)
    @patch("hr_data.legacy_api.LegacyReportAssetInventoryService")
    def test_invalid_limit_is_rejected_before_inventory(self, service_cls, _tenant):
        request = self.factory.get("/api/v1/hr/data/legacy/report-assets/?limit=bad")
        request.user = SuperuserStub()

        response = legacy_api.legacy_report_assets(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"INVALID_LIMIT", response.content)
        service_cls.assert_not_called()

    def test_non_get_is_rejected(self):
        request = self.factory.post("/api/v1/hr/data/legacy/report-assets/")
        request.user = SuperuserStub()

        response = legacy_api.legacy_report_assets(request)

        self.assertEqual(response.status_code, 405)
        self.assertIn(b"METHOD_NOT_ALLOWED", response.content)

    @patch("hr_data.legacy_api.resolve_request_tenant", return_value=7)
    @patch("hr_data.legacy_api.LegacyReportTakeoverService")
    def test_inventory_requires_takeover_permission_and_returns_evidence_step(
        self, service_cls, resolve_tenant
    ):
        step = SimpleNamespace(
            id=uuid.uuid4(),
            cutover_code="TAKEOVER_2026",
            step_no=1,
            phase="INVENTORIED",
            asset_count=3,
            matched_count=0,
            archived_count=0,
            unavailable_count=3,
            evidence_hash="a" * 64,
        )
        service_cls.return_value.inventory.return_value = SimpleNamespace(
            value=step, created=True
        )
        request = self.factory.post(
            "/api/v1/hr/data/legacy/report-takeover/inventory/",
            data=json.dumps(
                {
                    "cutoverCode": "TAKEOVER_2026",
                    "idempotencyKey": "inventory-1",
                }
            ),
            content_type="application/json",
        )
        request.user = SuperuserStub()

        response = legacy_api.inventory(request)

        self.assertEqual(response.status_code, 201)
        resolve_tenant.assert_called_once_with(
            request, required_permission="hr.data.legacy.takeover"
        )
        self.assertIn(b'"phase": "INVENTORIED"', response.content)
        self.assertIn(b'"evidenceHash"', response.content)

    @patch("hr_data.legacy_api.resolve_request_tenant", return_value=7)
    @patch("hr_data.legacy_api.LegacyReportTakeoverService")
    def test_reconcile_surfaces_unavailable_instead_of_faking_match(
        self, service_cls, _tenant
    ):
        result = SimpleNamespace(
            id=uuid.uuid4(),
            run_no="RUN_1",
            status="UNAVAILABLE",
            legacy_output_hash="",
            canonical_output_hash="",
            differences_json={},
            evidence_hash="b" * 64,
        )
        service_cls.return_value.reconcile.return_value = SimpleNamespace(
            value=result, created=True
        )
        asset_id = uuid.uuid4()
        request = self.factory.post(
            f"/api/v1/hr/data/legacy/report-takeover/assets/{asset_id}/reconcile/",
            data=json.dumps(
                {"runNo": "RUN_1", "idempotencyKey": "reconcile-1"}
            ),
            content_type="application/json",
        )
        request.user = SuperuserStub()

        response = legacy_api.reconcile_asset(request, asset_id)

        self.assertEqual(response.status_code, 201)
        self.assertIn(b'"status": "UNAVAILABLE"', response.content)
        self.assertNotIn(b'"status": "MATCHED"', response.content)
