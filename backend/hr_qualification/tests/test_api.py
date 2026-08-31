"""
tests/test_api.py —— API 层测试（总册 S11）。

覆盖：
- envelope 格式
- 错误信封格式
- credential list 接口
- tenant fail-closed
"""

from django.test import Client, TestCase

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
    """集成测试：端点在真实 selected-school + 鉴权合同下可用。"""

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from horilla.horilla_middlewares import _thread_locals
        from horilla_auth.models import HorillaUser

        self.client = Client()
        # A previous request-style test may have installed a user object that is
        # rolled back with its TestCase transaction. Company is a HorillaModel,
        # so carrying that stale actor into this new fixture would create an FK
        # to a user row that no longer exists. This setup is intentionally a
        # background/no-request boundary until _login_school() starts a request.
        _thread_locals.request = None
        self.company = Company.objects.create(
            company="HR09 API 测试大学",
            hq=True,
            address="测试路 9 号",
            country="CN",
            state="湖南",
            city="长沙",
            zip="410000",
        )
        self.admin = HorillaUser.objects.create_user(
            username="hr09_api_admin",
            email="hr09-api-admin@test.local",
            password="Admin123!",
            is_superuser=True,
            is_staff=True,
        )
        employee = Employee.objects.create(
            employee_user_id=self.admin,
            employee_first_name="HR09",
            employee_last_name="管理员",
            email=self.admin.email,
            phone="13800009009",
        )
        # 创建夹具时还没有请求 tenant context；仅用 base manager 绑定学校，
        # 避免 fail-closed manager 把初始化 update 静默过滤为 0 行。
        EmployeeWorkInformation._base_manager.filter(employee_id=employee).update(
            company_id_id=self.company.pk,
        )

    def _login_school(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session["selected_company"] = str(self.company.pk)
        session.save()

    def test_credential_list_requires_tenant(self):
        # 无服务端 selected_company 必须 fail-closed；query/body/header 均不得补 tenant。
        resp = self.client.get("/api/v1/hr/qualifications/credentials?tenant_id=999999")
        self.assertEqual(resp.status_code, 403)
        data = resp.json()
        self.assertEqual(data["error"]["code"], "TENANT_CONTEXT_REQUIRED")

    def test_credential_list_with_tenant(self):
        from hr_qualification.models import HrCredentialCatalogItem, HrPersonCredential
        from hr_staff.models import HrPerson

        self._login_school()
        person = HrPerson.objects.create(
            tenant_id=self.company.pk, legal_name="API资格测试人员"
        )
        catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=None, code="API-TEST", category="OTHER", name="API Test"
        )
        HrPersonCredential.objects.create(
            tenant_id=self.company.pk,
            person_id=person,
            credential_name_snapshot="API Cert",
            catalog_item_id=catalog,
            issuer_name="Issuer",
            status="DRAFT",
        )

        # tenant 不再来自 query；只使用服务端 selected_company。
        resp = self.client.get("/api/v1/hr/qualifications/credentials")
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        self.assertEqual(data["apiVersion"], "v1")
        self.assertIn("data", data)
        self.assertIn("items", data["data"])
        self.assertEqual(len(data["data"]["items"]), 1)

    def test_requirement_match_endpoint_uses_restored_authority_service(self):
        from hr_qualification.constants import CredentialCategory, CredentialStatus
        from hr_qualification.models import (
            HrCredentialCatalogItem,
            HrCredentialRequirement,
            HrPersonCredential,
        )
        from hr_staff.models import HrPerson

        self._login_school()
        person = HrPerson.objects.create(
            tenant_id=self.company.pk,
            legal_name="API requirement match",
        )
        catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=self.company.pk,
            code="API-REQ-MATCH",
            category=CredentialCategory.VOCATIONAL_QUALIFICATION,
            name="API Requirement Match",
            level_schema={"levels": [{"code": "LEVEL_2", "rank": 4}]},
        )
        credential = HrPersonCredential.objects.create(
            tenant_id=self.company.pk,
            person_id=person,
            credential_name_snapshot=catalog.name,
            catalog_item_id=catalog,
            issuer_name="Authority",
            level_code="LEVEL_2",
            status=CredentialStatus.ACTIVE,
        )
        requirement = HrCredentialRequirement.objects.create(
            tenant_id=self.company.pk,
            credential_category=CredentialCategory.VOCATIONAL_QUALIFICATION,
            catalog_item_id=catalog,
            minimum_level="LEVEL_2",
        )

        resp = self.client.get(
            f"/api/v1/hr/qualifications/credentials/{credential.id}/requirement-match"
        )

        self.assertEqual(resp.status_code, 200, resp.content[:500])
        items = resp.json()["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["requirement_id"], str(requirement.id))
        self.assertEqual(items[0]["result"], "MET")
        self.assertEqual(items[0]["matched_credential_id"], str(credential.id))

    def test_catalog_list(self):
        self._login_school()
        resp = self.client.get("/api/v1/hr/qualifications/catalog")
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        self.assertIn("items", data["data"])

    def test_batch_list(self):
        self._login_school()
        resp = self.client.get("/api/v1/hr/qualifications/double-teacher/batches")
        self.assertEqual(resp.status_code, 200, resp.content[:300])

    def test_batch_advance_follows_canonical_sequence(self):
        import json
        from datetime import date

        from hr_qualification.constants import BatchStatus, RulePackVersionStatus
        from hr_qualification.models import (
            HrDoubleTeacherRecognitionBatch,
            HrDoubleTeacherRulePack,
            HrDoubleTeacherRulePackVersion,
        )

        self._login_school()
        pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=self.company.pk,
            code="API-BATCH-FLOW",
            name="API 批次流程规则",
        )
        version = HrDoubleTeacherRulePackVersion.objects.create(
            rule_pack_id=pack,
            version_no=1,
            effective_from=date.today(),
            status=RulePackVersionStatus.ACTIVE,
            checksum="sealed-test-version",
        )
        batch = HrDoubleTeacherRecognitionBatch.objects.create(
            tenant_id=self.company.pk,
            batch_no="API-BATCH-001",
            name="API 批次流程",
            rule_pack_version_id=version,
            target_levels=["DOUBLE_TEACHER_JUNIOR"],
        )

        expected = [
            BatchStatus.PUBLISHED,
            BatchStatus.APPLICATION_OPEN,
            BatchStatus.APPLICATION_CLOSED,
            BatchStatus.REVIEWING,
            BatchStatus.RESULT_PENDING,
            BatchStatus.RESULT_PUBLISHED,
            BatchStatus.CLOSED,
        ]
        for status in expected:
            response = self.client.post(
                f"/api/v1/hr/qualifications/double-teacher/batches/{batch.id}/advance",
                data=json.dumps({}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200, response.content[:500])
            self.assertEqual(response.json()["data"]["status"], status)

        terminal = self.client.post(
            f"/api/v1/hr/qualifications/double-teacher/batches/{batch.id}/advance",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(terminal.status_code, 409)
        self.assertEqual(terminal.json()["error"]["code"], "BATCH_TERMINAL_STATE")

    def test_batch_create_rejects_other_school_rule_version(self):
        import json
        from datetime import date

        from hr_qualification.constants import RulePackVersionStatus
        from hr_qualification.models import (
            HrDoubleTeacherRulePack,
            HrDoubleTeacherRulePackVersion,
        )

        self._login_school()
        other_pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=self.company.pk + 999,
            code="OTHER-SCHOOL-RULE",
            name="其它学校规则",
        )
        other_version = HrDoubleTeacherRulePackVersion.objects.create(
            rule_pack_id=other_pack,
            version_no=1,
            effective_from=date.today(),
            status=RulePackVersionStatus.ACTIVE,
        )
        response = self.client.post(
            "/api/v1/hr/qualifications/double-teacher/batches/create",
            data=json.dumps(
                {
                    "batch_no": "CROSS-TENANT",
                    "name": "不应创建",
                    "rule_pack_version_id": str(other_version.id),
                    "target_levels": ["DOUBLE_TEACHER_JUNIOR"],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "RULE_VERSION_NOT_AVAILABLE")
