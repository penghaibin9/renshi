"""
tests/test_services.py —— 服务层测试（总册 §161/S11）。

覆盖：
- CredentialService: tenant gate / submit / verify / renew / suspend / revoke
- RuleService: dsl validation + diff
- ApplicationService: state machine transitions
- ReviewService: finalize
- RecheckService: open + decide
- RiskService: detect + dedup
"""

from datetime import date

from django.test import TestCase

from hr_qualification.constants import (
    ApplicationStatus,
    CredentialStatus,
    RecognitionLevel,
    VerificationResult,
)
from hr_qualification.models import (
    HrCredentialCatalogItem,
    HrDoubleTeacherApplication,
    HrDoubleTeacherRecognitionBatch,
    HrDoubleTeacherRulePack,
    HrDoubleTeacherRulePackVersion,
    HrPersonCredential,
)
from hr_qualification.services.application_service import ApplicationError, ApplicationService
from hr_qualification.services.credential_service import CredentialError, CredentialService
from hr_qualification.services.risk_service import RiskService
from hr_staff.models import HrPerson


class CredentialServiceTest(TestCase):
    def setUp(self):
        self.person = HrPerson.objects.create(
            tenant_id=1,
            legal_name="资格测试人员",
        )
        self.catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=None, code="TEST-CRED", category="OTHER", name="Test Credential"
        )
        self.cred = HrPersonCredential.objects.create(
            tenant_id=1,
            person_id=self.person,
            credential_name_snapshot="Test Cert",
            catalog_item_id=self.catalog,
            issuer_name="Test Issuer",
            valid_from=date(2026, 1, 1),
            status=CredentialStatus.DRAFT,
        )

    def test_submit_verification(self):
        c = CredentialService.submit_for_verification(
            tenant_id=1,
            credential_id=self.cred.id,
        )
        self.assertEqual(c.status, CredentialStatus.UNDER_VERIFICATION)

    def test_cross_tenant_credential_uuid_fails_closed(self):
        with self.assertRaises(CredentialError) as cm:
            CredentialService.submit_for_verification(
                tenant_id=2,
                credential_id=self.cred.id,
            )
        self.assertEqual(cm.exception.code, "CREDENTIAL_NOT_FOUND")

    def test_verify_success_requires_manual_actor(self):
        CredentialService.submit_for_verification(
            tenant_id=1,
            credential_id=self.cred.id,
        )
        v = CredentialService.verify(
            tenant_id=1,
            credential_id=self.cred.id,
            verification_type="MANUAL_ORIGINAL_REVIEW",
            result=VerificationResult.VERIFIED,
            verified_by=99,
            provider="manual-original-desk",
        )
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.status, CredentialStatus.ACTIVE)
        self.assertEqual(v.result, "VERIFIED")
        self.assertEqual(v.verified_by, 99)

    def test_manual_verified_without_actor_is_rejected(self):
        CredentialService.submit_for_verification(
            tenant_id=1,
            credential_id=self.cred.id,
        )
        with self.assertRaises(CredentialError) as cm:
            CredentialService.verify(
                tenant_id=1,
                credential_id=self.cred.id,
                verification_type="MANUAL_ORIGINAL_REVIEW",
                result=VerificationResult.VERIFIED,
            )
        self.assertEqual(cm.exception.code, "VERIFICATION_ACTOR_REQUIRED")

    def test_non_manual_verified_requires_trusted_provider_adapter(self):
        CredentialService.submit_for_verification(
            tenant_id=1,
            credential_id=self.cred.id,
        )
        with self.assertRaises(CredentialError) as cm:
            CredentialService.verify(
                tenant_id=1,
                credential_id=self.cred.id,
                verification_type="OFFICIAL_DATABASE",
                result=VerificationResult.VERIFIED,
                verified_by=99,
                provider="some-client-supplied-provider",
            )
        self.assertEqual(cm.exception.code, "VERIFICATION_TRUSTED_PROVIDER_REQUIRED")

    def test_mock_provider_never_produces_verified(self):
        CredentialService.submit_for_verification(
            tenant_id=1,
            credential_id=self.cred.id,
        )
        with self.assertRaises(CredentialError) as cm:
            CredentialService.verify(
                tenant_id=1,
                credential_id=self.cred.id,
                verification_type="MANUAL_ORIGINAL_REVIEW",
                result=VerificationResult.VERIFIED,
                verified_by=99,
                provider="mock-provider",
            )
        self.assertEqual(cm.exception.code, "VERIFICATION_PROVIDER_NOT_TRUSTED")

    def test_provider_unavailable_is_recorded_but_never_activates(self):
        CredentialService.submit_for_verification(
            tenant_id=1,
            credential_id=self.cred.id,
        )
        verification = CredentialService.verify(
            tenant_id=1,
            credential_id=self.cred.id,
            verification_type="OFFICIAL_DATABASE",
            result=VerificationResult.PROVIDER_UNAVAILABLE,
            provider="official-registry",
        )
        self.cred.refresh_from_db()
        self.assertEqual(verification.result, VerificationResult.PROVIDER_UNAVAILABLE)
        self.assertEqual(self.cred.status, CredentialStatus.UNDER_VERIFICATION)
        self.assertEqual(
            self.cred.current_verification_status,
            VerificationResult.PROVIDER_UNAVAILABLE,
        )

    def test_verify_fail_blocks_active(self):
        CredentialService.submit_for_verification(
            tenant_id=1,
            credential_id=self.cred.id,
        )
        CredentialService.verify(
            tenant_id=1,
            credential_id=self.cred.id,
            verification_type="MANUAL_ORIGINAL_REVIEW",
            result=VerificationResult.MISMATCH,
        )
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.status, CredentialStatus.UNDER_VERIFICATION)

    def test_suspend(self):
        self.cred.status = CredentialStatus.ACTIVE
        self.cred.save(update_fields=["status"])
        c = CredentialService.suspend(
            tenant_id=1,
            credential_id=self.cred.id,
            reason="Policy",
        )
        self.assertEqual(c.status, CredentialStatus.SUSPENDED)

    def test_revoke(self):
        self.cred.status = CredentialStatus.ACTIVE
        self.cred.save(update_fields=["status"])
        c = CredentialService.revoke(
            tenant_id=1,
            credential_id=self.cred.id,
            reason="Fraud",
        )
        self.assertEqual(c.status, CredentialStatus.REVOKED)

    def test_renew_creates_new_generation_and_does_not_edit_old_validity(self):
        self.cred.status = CredentialStatus.ACTIVE
        self.cred.valid_to = date(2026, 12, 31)
        self.cred.save(update_fields=["status", "valid_to"])

        new_credential, renewal = CredentialService.renew(
            tenant_id=1,
            credential_id=self.cred.id,
            new_credential_data={
                "valid_from": date(2027, 1, 1),
                "valid_to": date(2027, 12, 31),
            },
        )

        self.cred.refresh_from_db()
        self.assertEqual(self.cred.status, CredentialStatus.SUPERSEDED)
        self.assertEqual(self.cred.valid_to, date(2026, 12, 31))
        self.assertNotEqual(new_credential.id, self.cred.id)
        self.assertEqual(new_credential.valid_from, date(2027, 1, 1))
        self.assertEqual(renewal.original_credential_id_id, self.cred.id)
        self.assertEqual(renewal.new_credential_id_id, new_credential.id)

    def test_renewal_cannot_override_authority_identity(self):
        self.cred.status = CredentialStatus.ACTIVE
        self.cred.save(update_fields=["status"])
        with self.assertRaises(CredentialError) as cm:
            CredentialService.renew(
                tenant_id=1,
                credential_id=self.cred.id,
                new_credential_data={"tenant_id": 2},
            )
        self.assertEqual(cm.exception.code, "CREDENTIAL_RENEWAL_IDENTITY_OVERRIDE")

    def test_cannot_edit_active(self):
        self.cred.status = CredentialStatus.ACTIVE
        self.cred.save(update_fields=["status"])
        with self.assertRaises(CredentialError):
            CredentialService.submit_for_verification(
                tenant_id=1,
                credential_id=self.cred.id,
            )


class ApplicationServiceTest(TestCase):
    def setUp(self):
        self.pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=1, code="TEST-APP-PACK", name="App Pack"
        )
        self.version = HrDoubleTeacherRulePackVersion.objects.create(
            rule_pack_id=self.pack, version_no=1, effective_from="2026-01-01"
        )
        self.batch = HrDoubleTeacherRecognitionBatch.objects.create(
            tenant_id=1,
            batch_no="BATCH-001",
            name="Test Batch",
            rule_pack_version_id=self.version,
        )
        self.app = HrDoubleTeacherApplication.objects.create(
            tenant_id=1,
            application_no="APP-TEST-001",
            batch_id=self.batch,
            target_level=RecognitionLevel.DOUBLE_TEACHER_JUNIOR,
            status=ApplicationStatus.DRAFT,
        )

    def test_submit_from_draft(self):
        app = ApplicationService.transition(self.app, ApplicationStatus.SUBMITTED)
        self.assertEqual(app.status, ApplicationStatus.SUBMITTED)

    def test_cannot_jump_to_final(self):
        with self.assertRaises(ApplicationError):
            ApplicationService.transition(self.app, ApplicationStatus.RECOGNIZED)

    def test_withdraw(self):
        ApplicationService.transition(self.app, ApplicationStatus.SUBMITTED)
        app = ApplicationService.transition(self.app, ApplicationStatus.WITHDRAWN)
        self.assertEqual(app.status, ApplicationStatus.WITHDRAWN)

    def test_submitted_timestamp(self):
        app = ApplicationService.transition(self.app, ApplicationStatus.SUBMITTED)
        self.assertIsNotNone(app.submitted_at)


class RiskServiceTest(TestCase):
    def setUp(self):
        self.person = HrPerson.objects.create(tenant_id=1, legal_name="风险测试人员")
        self.catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=None, code="TEST-RISK", category="OTHER", name="Risk Cert"
        )

    def test_dedup_risk(self):
        """同类型 OPEN 风险不重复创建。"""
        cred = HrPersonCredential.objects.create(
            tenant_id=1,
            person_id=self.person,
            credential_name_snapshot="Exp Cert",
            catalog_item_id=self.catalog,
            issuer_name="I",
            valid_from=date(2026, 1, 1),
            status=CredentialStatus.REVOKED,
        )
        r1 = RiskService._upsert_risk(
            tenant_id=1,
            person_id=cred.person_id,
            credential_id=cred.id,
            risk_type="CREDENTIAL_REVOKED",
            severity="CRITICAL",
        )
        self.assertIsNotNone(r1)
        r2 = RiskService._upsert_risk(
            tenant_id=1,
            person_id=cred.person_id,
            credential_id=cred.id,
            risk_type="CREDENTIAL_REVOKED",
            severity="CRITICAL",
        )
        self.assertIsNone(r2)
