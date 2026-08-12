"""
tests/test_api.py —— API 层测试（总册 S11）。

覆盖：
- envelope 格式
- 错误信封格式
- credential list 接口
- tenant fail-closed
"""

from django.test import TestCase, Client

from hr_qualification.api.serializers import envelope, error_envelope


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
    """集成测试：API 端点路由是否存在。"""

    def setUp(self):
        self.client = Client()

    def test_credential_list_requires_tenant(self):
        resp = self.client.get("/api/v1/hr/qualifications/credentials")
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertEqual(data["error"]["code"], "TENANT_CONTEXT_REQUIRED")

    def test_credential_list_with_tenant(self):
        from hr_qualification.models import HrCredentialCatalogItem, HrPersonCredential
        from hr_staff.models import HrPerson

        person = HrPerson.objects.create(tenant_id=1, legal_name="API资格测试人员")
        catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=None, code="API-TEST", category="OTHER", name="API Test"
        )
        HrPersonCredential.objects.create(
            tenant_id=1,
            person_id=person,
            credential_name_snapshot="API Cert",
            catalog_item_id=catalog,
            issuer_name="Issuer",
            status="DRAFT",
        )

        resp = self.client.get("/api/v1/hr/qualifications/credentials?tenant_id=1")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["apiVersion"], "v1")
        self.assertIn("data", data)
        self.assertIn("items", data["data"])

    def test_catalog_list(self):
        resp = self.client.get("/api/v1/hr/qualifications/catalog")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data["data"])

    def test_batch_list(self):
        resp = self.client.get("/api/v1/hr/qualifications/double-teacher/batches?tenant_id=1")
        self.assertEqual(resp.status_code, 200)
