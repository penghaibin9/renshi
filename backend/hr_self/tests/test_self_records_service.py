from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from hr_self.services.identity_service import SelfIdentityContext
from hr_self.services.provider_gateway import (
    ProviderStatus,
    SelfProviderRegistry,
    SelfProviderResult,
)
from hr_self.services.self_records_service import (
    SelfRecordsService,
    hr03_controlled_files_provider,
)


class Hr17ControlledFilesProviderTests(SimpleTestCase):
    def setUp(self):
        self.context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id="00000000-0000-0000-0000-000000000301",
            person_id="00000000-0000-0000-0000-000000000201",
            legacy_employee_id=51,
        )
        self.updated_at = datetime(2026, 8, 15, 1, 2, 3, tzinfo=timezone.utc)

    @patch("hr_staff.models.HrStaffMaterialVersion")
    @patch("hr_staff.models.HrStaffMaterial")
    def test_directory_is_self_tenant_scoped_and_hides_storage_secrets(
        self,
        material_model,
        version_model,
    ):
        material = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000311",
            title="教师资格证明",
            category_code="QUALIFICATION",
            sensitivity_level="RESTRICTED_HR",
            verification_status="VERIFIED",
            current_version_id="00000000-0000-0000-0000-000000000312",
            source="HR09",
            related_fact_type="CREDENTIAL",
            updated_at=self.updated_at,
        )
        version = SimpleNamespace(
            id=material.current_version_id,
            version_no=2,
            storage_file_id="private://secret-bucket/key",
            legacy_document_id=999,
            original_filename="contains-private-id-number.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            sha256="secret-hash",
            issue_date=date(2025, 1, 1),
            expiry_date=None,
            uploaded_by=123,
            uploaded_at=self.updated_at,
            verified_by=456,
            verified_at=self.updated_at,
            status="CURRENT",
            created_at=self.updated_at,
        )
        material_model.objects.filter.return_value.order_by.return_value.__getitem__.return_value = [
            material
        ]
        version_model.objects.filter.return_value.order_by.return_value = [version]

        result = hr03_controlled_files_provider(self.context)

        material_model.objects.filter.assert_called_once_with(
            tenant_id=77,
            staff_id=self.context.staff_id,
        )
        version_model.objects.filter.assert_called_once_with(
            tenant_id=77,
            id__in=[material.current_version_id],
        )
        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.meta["authority"], "HR03_STAFF_AUTHORITY")
        item = result.data["files"][0]
        self.assertEqual(item["currentVersion"]["contentAccess"], "CONTROLLED_TICKET")
        self.assertEqual(item["evidence"]["versionNo"], 2)
        rendered = repr(item)
        for secret in (
            "private://secret-bucket/key",
            "secret-hash",
            "contains-private-id-number.pdf",
            "legacyDocumentId",
            "uploadedBy",
            "verifiedBy",
        ):
            self.assertNotIn(secret, rendered)


class Hr17SelfRecordsServiceTests(SimpleTestCase):
    def setUp(self):
        self.context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id="00000000-0000-0000-0000-000000000301",
            person_id="00000000-0000-0000-0000-000000000201",
            legacy_employee_id=51,
        )
        self.updated_at = datetime(2026, 8, 15, 1, 2, 3, tzinfo=timezone.utc)

    def test_projects_versioned_contract_and_terminal_payslip_summaries(self):
        registry = SelfProviderRegistry()
        registry.register(
            "HR07",
            lambda context: SelfProviderResult.ok(
                {
                    "contractAgreements": [
                        {
                            "id": "agreement-1",
                            "agreementNo": "HT-2026-001",
                            "title": "教师聘用合同",
                            "type": "EMPLOYMENT",
                            "status": "ACTIVE",
                            "currentVersionNo": 3,
                            "updatedAt": self.updated_at.isoformat(),
                            "signedDocumentRef": "must-not-pass-through",
                        }
                    ]
                },
                source_updated_at=self.updated_at,
                provider_version="hr07-test.3",
                meta={"authority": "HR07_CONTRACT_AUTHORITY"},
            ),
        )
        registry.register(
            "HR15",
            lambda context: SelfProviderResult.ok(
                {
                    "payrollResults": [
                        {
                            "id": "result-final",
                            "resultNo": "PAY-2026-08-001",
                            "periodCode": "2026-08",
                            "currencyCode": "CNY",
                            "grossAmount": "10000.00",
                            "deductionAmount": "1200.00",
                            "netAmount": "8800.00",
                            "status": "FINALIZED",
                            "createdAt": self.updated_at.isoformat(),
                            "updatedAt": self.updated_at.isoformat(),
                            "paymentAccountRef": "must-not-pass-through",
                        },
                        {
                            "id": "result-draft",
                            "resultNo": "DRAFT-1",
                            "status": "DRAFT",
                        },
                    ]
                },
                source_updated_at=self.updated_at,
                provider_version="hr15-test.4",
                meta={"authority": "HR15_PAYROLL_AUTHORITY"},
            ),
        )
        files_provider = lambda context: SelfProviderResult.ok(
            {"files": []},
            provider_version="hr03-test.2",
        )

        payload = SelfRecordsService(
            self.context,
            registry=registry,
            files_provider=files_provider,
        ).build()

        self.assertEqual(payload["files"], [])
        self.assertEqual(payload["contracts"][0]["evidence"]["versionNo"], 3)
        self.assertNotIn("signedDocumentRef", payload["contracts"][0])
        self.assertEqual([row["id"] for row in payload["payslips"]], ["result-final"])
        self.assertNotIn("paymentAccountRef", payload["payslips"][0])
        self.assertEqual(
            payload["payslips"][0]["evidence"]["providerVersion"],
            "hr15-test.4",
        )
        self.assertFalse(payload["degraded"])

    def test_one_source_failure_is_explicit_and_does_not_erase_other_sources(self):
        registry = SelfProviderRegistry()
        registry.register("HR07", lambda context: (_ for _ in ()).throw(RuntimeError("down")))
        registry.register(
            "HR15",
            lambda context: SelfProviderResult.ok(
                {"payrollResults": []},
                provider_version="hr15-test.1",
            ),
        )

        payload = SelfRecordsService(
            self.context,
            registry=registry,
            files_provider=lambda context: SelfProviderResult.unavailable(
                "FILES_BACKEND_DOWN",
                provider_version="hr03-files-test.1",
            ),
        ).build()

        self.assertIsNone(payload["files"])
        self.assertIsNone(payload["contracts"])
        self.assertEqual(payload["payslips"], [])
        self.assertEqual(
            payload["sourceHealth"]["HR03_FILES"]["status"],
            ProviderStatus.UNAVAILABLE,
        )
        self.assertEqual(
            payload["sourceHealth"]["HR07_CONTRACTS"]["status"],
            ProviderStatus.ERROR,
        )
        self.assertIn("HR03_FILES", payload["degradedSources"])
        self.assertIn("HR07_CONTRACTS", payload["degradedSources"])

    def test_invalid_files_provider_is_not_accepted_as_empty_business_data(self):
        payload = SelfRecordsService(
            self.context,
            registry=SelfProviderRegistry(),
            files_provider=lambda context: {"files": []},
        ).build()

        self.assertIsNone(payload["files"])
        self.assertEqual(
            payload["sourceHealth"]["HR03_FILES"]["errorCode"],
            "SOURCE_PROVIDER_CONTRACT_INVALID",
        )
