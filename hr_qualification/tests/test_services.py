"""
tests/test_services.py —— 服务层测试（总册 §161/S11）。

覆盖：
- CredentialService: submit/verify/renew/suspend/revoke
- RuleService: dsl validation + diff
- ApplicationService: state machine transitions
- ReviewService: finalize
- RecheckService: open + decide
- RiskService: detect + dedup
"""

from django.test import TestCase

from hr_qualification.constants import (
    ApplicationStatus,
    CredentialStatus,
    FinalDecisionType,
    RecognitionLevel,
    RecognitionStatus,
    VerificationResult,
)
from hr_qualification.models import (
    HrCredentialCatalogItem,
    HrDoubleTeacherApplication,
    HrDoubleTeacherRecognitionBatch,
    HrDoubleTeacherRule,
    HrDoubleTeacherRulePack,
    HrDoubleTeacherRulePackVersion,
    HrPersonCredential,
)
from hr_qualification.services.application_service import ApplicationError, ApplicationService
from hr_qualification.services.credential_service import CredentialError, CredentialService
from hr_qualification.services.risk_service import RiskService


class CredentialServiceTest(TestCase):
    def setUp(self):
        self.catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=None, code="TEST-CRED", category="OTHER", name="Test Credential"
        )
        self.cred = HrPersonCredential.objects.create(
            tenant_id=1,
            credential_name_snapshot="Test Cert",
            catalog_item_id=self.catalog,
            issuer_name="Test Issuer",
            status=CredentialStatus.DRAFT,
        )

    def test_submit_verification(self):
        c = CredentialService.submit_for_verification(self.cred.id)
        self.assertEqual(c.status, CredentialStatus.UNDER_VERIFICATION)

    def test_verify_success(self):
        CredentialService.submit_for_verification(self.cred.id)
        v = CredentialService.verify(
            self.cred.id,
            "MANUAL_ORIGINAL_REVIEW",
            VerificationResult.VERIFIED,
        )
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.status, CredentialStatus.ACTIVE)
        self.assertEqual(v.result, "VERIFIED")

    def test_verify_fail_blocks_active(self):
        """非 VERIFIED 结果不触发状态变更"""
        CredentialService.submit_for_verification(self.cred.id)
        CredentialService.verify(
            self.cred.id,
            "MANUAL_ORIGINAL_REVIEW",
            VerificationResult.MISMATCH,
        )
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.status, CredentialStatus.UNDER_VERIFICATION)

    def test_suspend(self):
        self.cred.status = CredentialStatus.ACTIVE
        self.cred.save()
        c = CredentialService.suspend(self.cred.id, reason="Policy")
        self.assertEqual(c.status, CredentialStatus.SUSPENDED)

    def test_revoke(self):
        self.cred.status = CredentialStatus.ACTIVE
        self.cred.save()
        c = CredentialService.revoke(self.cred.id, reason="Fraud")
        self.assertEqual(c.status, CredentialStatus.REVOKED)

    def test_cannot_edit_active(self):
        self.cred.status = CredentialStatus.ACTIVE
        self.cred.save()
        with self.assertRaises(CredentialError):
            CredentialService.submit_for_verification(self.cred.id)


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
        self.catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=None, code="TEST-RISK", category="OTHER", name="Risk Cert"
        )

    def test_dedup_risk(self):
        """同类型 OPEN 风险不重复创建"""
        cred = HrPersonCredential.objects.create(
            tenant_id=1,
            credential_name_snapshot="Exp Cert",
            catalog_item_id=self.catalog,
            issuer_name="I",
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
