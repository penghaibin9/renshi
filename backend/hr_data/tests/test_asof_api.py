import json
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import RequestFactory, SimpleTestCase, TestCase

from hr_data import asof_api


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88


class AsOfPermissionMigrationTests(TestCase):
    def test_asof_and_quality_permissions_exist_after_migrate(self):
        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="hr_data",
                content_type__model="metricdefinitionversion",
                codename="hr.data.asof",
            ).exists()
        )
        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="hr_data",
                content_type__model="metricdefinitionversion",
                codename="hr.data.quality",
            ).exists()
        )


class AsOfApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    def _evidence():
        return SimpleNamespace(
            id=uuid.uuid4(),
            evidence_no="E-1",
            definition_kind="METRIC",
            definition_code="HEADCOUNT",
            definition_version=2,
            as_of_date=date(2026, 8, 1),
            status="COMPLETE",
            source_statuses_json={"HR03": "OK"},
            blocked_domains_json=[],
            provider_versions_json={"HR03": "v7"},
            provider_evidence_hashes_json={"HR03": "a" * 64},
            evidence_hash="b" * 64,
            generated_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        )

    @patch("hr_data.asof_api.AsOfReconstructionService")
    @patch("hr_data.asof_api.resolve_request_tenant", return_value=77)
    def test_reconstruct_uses_dedicated_permission_and_canonical_service(
        self, tenant_resolver, service_cls
    ):
        service_cls.return_value.reconstruct.return_value = SimpleNamespace(
            evidence=self._evidence(), created=True
        )
        request = self.factory.post(
            "/api/v1/hr/data/as-of/evidence/",
            data=json.dumps(
                {
                    "evidenceNo": "E-1",
                    "definitionKind": "METRIC",
                    "definitionCode": "HEADCOUNT",
                    "definitionVersion": 2,
                    "asOfDate": "2026-08-01",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = asof_api.reconstruct_evidence(request)

        self.assertEqual(response.status_code, 201)
        tenant_resolver.assert_called_once_with(
            request,
            required_permission=asof_api.ASOF_PERMISSION,
        )
        kwargs = service_cls.return_value.reconstruct.call_args.kwargs
        self.assertEqual(kwargs["definition_kind"], "METRIC")
        self.assertEqual(kwargs["as_of_date"], date(2026, 8, 1))
        self.assertIn(b'"providerEvidenceHashes"', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_data.asof_api.AsOfReconstructionService")
    @patch("hr_data.asof_api.resolve_request_tenant", return_value=77)
    def test_invalid_date_never_calls_reconstruction(self, _tenant, service_cls):
        request = self.factory.post(
            "/api/v1/hr/data/as-of/evidence/",
            data=json.dumps(
                {
                    "evidenceNo": "E-1",
                    "definitionKind": "METRIC",
                    "definitionCode": "HEADCOUNT",
                    "definitionVersion": 2,
                    "asOfDate": "not-a-date",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()
        response = asof_api.reconstruct_evidence(request)
        self.assertEqual(response.status_code, 400)
        service_cls.assert_not_called()

    @patch("hr_data.asof_api.AsOfReconstructionService")
    @patch("hr_data.asof_api.resolve_request_tenant", return_value=77)
    def test_unavailable_evidence_is_returned_as_real_result_not_fake_complete(
        self, _tenant, service_cls
    ):
        evidence = self._evidence()
        evidence.status = "UNAVAILABLE"
        evidence.source_statuses_json = {"HR03": "UNAVAILABLE"}
        evidence.blocked_domains_json = ["HR03"]
        service_cls.return_value.reconstruct.return_value = SimpleNamespace(
            evidence=evidence, created=True
        )
        request = self.factory.post(
            "/api/v1/hr/data/as-of/evidence/",
            data=json.dumps(
                {
                    "evidenceNo": "E-2",
                    "definitionKind": "METRIC",
                    "definitionCode": "HEADCOUNT",
                    "definitionVersion": 2,
                    "asOfDate": "2026-08-01",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()
        response = asof_api.reconstruct_evidence(request)
        self.assertEqual(response.status_code, 201)
        self.assertIn(b'"status": "UNAVAILABLE"', response.content)
        self.assertNotIn(b'"status": "COMPLETE"', response.content)
