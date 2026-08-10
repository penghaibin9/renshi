"""
tests/test_api.py —— API 层测试（总册 S11）。

覆盖：
- envelope / error envelope
- tenant fail-closed
- credential UUID IDOR
- catalog 当前租户隔离
- 匿名请求不得自证 VERIFIED
"""

from datetime import date

from django.test import Client, TestCase

from hr_qualification.api.serializers import envelope, error_envelope
from hr_qualification.models import HrCredentialCatalogItem, HrPersonCredential
from hr_staff.models import HrPerson


class APIEnvelopeTest(TestCase):
    def test_envelope_structure(self):
        result = envelope({"key": "value"})
        self.assertEqual(result["apiVersion"], "v1")
        self.assertEqual(result["schemaVersion"], "hr09.1")
        self.assertIn("requestId", result)
        self.assertEqual(result["data"], {"key": "value"})

    def test_error_envelope_structure(self):
        result = error_envelope("TEST_ERROR", "Something went wrong")
        self.assertEqual(result["error"]["code"], "TEST_ERROR")
        self.assertEqual(result["error"]["message"], "Something went wrong")
        self.assertIn("requestId", result)

    def test_error_envelope_retryable(self):
        result = error_envelope("ERR", "msg", retryable=True)
        self.assertTrue(result["error"]["retryable"])
        result2 = error_envelope("ERR", "msg")
        self.assertFalse(result2["error"]["retryable"])


class ResourceEndpointTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.person = HrPerson.objects.create(tenant_id=1, legal_name="API 测试人员")
        self.catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=None,
            code="API-TEST",
            category="OTHER",
            name="API Test",
        )
        self.credential = HrPersonCredential.objects.create(
            tenant_id=1,
            person_id=self.person,
            credential_name_snapshot="API Test",
            catalog_item_id=self.catalog,
            issuer_name="Issuer",
            valid_from=date(2026, 1, 1),
            status="DRAFT",
        )

    def test_credential_list_requires_tenant(self):
        resp = self.client.get("/api/v1/hr/qualifications/credentials")
        self.assertEqual(resp.status_code, 400)
        self.assertIn(resp.json()["error"]["code"], {"TENANT_CONTEXT_REQUIRED", "VALIDATION_ERROR"})

    def test_credential_list_with_tenant(self):
        resp = self.client.get(
            "/api/v1/hr/qualifications/credentials",
            HTTP_X_TENANT_ID="1",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["apiVersion"], "v1")
        self.assertEqual(data["data"]["total"], 1)
        self.assertEqual(data["data"]["items"][0]["id"], str(self.credential.id))

    def test_credential_detail_cross_tenant_uuid_is_not_found(self):
        resp = self.client.get(
            f"/api/v1/hr/qualifications/credentials/{self.credential.id}",
            HTTP_X_TENANT_ID="2",
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "CREDENTIAL_NOT_FOUND")

    def test_catalog_requires_tenant_and_does_not_read_other_tenant_extensions(self):
        HrCredentialCatalogItem.objects.create(
            tenant_id=2,
            code="TENANT-2-ONLY",
            category="OTHER",
            name="Other school catalog",
        )
        missing = self.client.get("/api/v1/hr/qualifications/catalog")
        self.assertEqual(missing.status_code, 400)

        resp = self.client.get(
            "/api/v1/hr/qualifications/catalog",
            HTTP_X_TENANT_ID="1",
        )
        self.assertEqual(resp.status_code, 200)
        codes = {item["code"] for item in resp.json()["data"]["items"]}
        self.assertIn("API-TEST", codes)
        self.assertNotIn("TENANT-2-ONLY", codes)

    def test_anonymous_manual_verified_cannot_activate_credential(self):
        submit = self.client.post(
            f"/api/v1/hr/qualifications/credentials/{self.credential.id}/submit-verification",
            data="{}",
            content_type="application/json",
            HTTP_X_TENANT_ID="1",
        )
        self.assertEqual(submit.status_code, 200)

        verify = self.client.post(
            f"/api/v1/hr/qualifications/credentials/{self.credential.id}/verify",
            data=(
                '{"verification_type":"MANUAL_ORIGINAL_REVIEW",'
                '"result":"VERIFIED","provider":"manual-original-desk"}'
            ),
            content_type="application/json",
            HTTP_X_TENANT_ID="1",
        )
        self.assertEqual(verify.status_code, 400)
        self.credential.refresh_from_db()
        self.assertEqual(self.credential.status, "UNDER_VERIFICATION")

    def test_batch_list(self):
        resp = self.client.get(
            "/api/v1/hr/qualifications/double-teacher/batches?tenant_id=1"
        )
        self.assertEqual(resp.status_code, 200)
