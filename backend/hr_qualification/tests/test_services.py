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
from hr_staff.models import HrPerson


class CredentialServiceTest(TestCase):
    def setUp(self):
        self.person = HrPerson.objects.create(tenant_id=1, legal_name="资格测试人员")
        self.catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=None, code="TEST-CRED", category="OTHER", name="Test Credential"
        )
        self.cred = HrPersonCredential.objects.create(
            tenant_id=1,
            person_id=self.person,
            credential_name_snapshot="Test Cert",
            catalog_item_id=self.catalog,
            issuer_name="Test Issuer",
            status=CredentialStatus.DRAFT,
        )

    def test_submit_verification(self):
        c = CredentialService.submit_for_verification(self.cred.id, tenant_id=1)
        self.assertEqual(c.status, CredentialStatus.UNDER_VERIFICATION)

    def test_verify_success(self):
        CredentialService.submit_for_verification(self.cred.id, tenant_id=1)
        v = CredentialService.verify(
            self.cred.id,
            "MANUAL_ORIGINAL_REVIEW",
            VerificationResult.VERIFIED,
            tenant_id=1,
        )
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.status, CredentialStatus.ACTIVE)
        self.assertEqual(v.result, "VERIFIED")

    def test_verify_fail_blocks_active(self):
        """非 VERIFIED 结果不触发状态变更"""
        CredentialService.submit_for_verification(self.cred.id, tenant_id=1)
        CredentialService.verify(
            self.cred.id,
            "MANUAL_ORIGINAL_REVIEW",
            VerificationResult.MISMATCH,
            tenant_id=1,
        )
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.status, CredentialStatus.UNDER_VERIFICATION)

    def test_suspend(self):
        self.cred.status = CredentialStatus.ACTIVE
        self.cred.save()
        c = CredentialService.suspend(self.cred.id, tenant_id=1, reason="Policy")
        self.assertEqual(c.status, CredentialStatus.SUSPENDED)

    def test_revoke(self):
        self.cred.status = CredentialStatus.ACTIVE
        self.cred.save()
        c = CredentialService.revoke(self.cred.id, tenant_id=1, reason="Fraud")
        self.assertEqual(c.status, CredentialStatus.REVOKED)

    def test_cannot_edit_active(self):
        self.cred.status = CredentialStatus.ACTIVE
        self.cred.save()
        with self.assertRaises(CredentialError):
            CredentialService.submit_for_verification(self.cred.id, tenant_id=1)

    def test_wrong_tenant_service_lookup_is_fail_closed(self):
        with self.assertRaises(CredentialError) as caught:
            CredentialService.submit_for_verification(self.cred.id, tenant_id=2)

        self.assertIn("not found inside tenant", str(caught.exception))
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.status, CredentialStatus.DRAFT)

    def test_renewal_cannot_replace_authority_lineage(self):
        self.cred.status = CredentialStatus.ACTIVE
        self.cred.save(update_fields=["status", "updated_at"])

        with self.assertRaises(CredentialError) as caught:
            CredentialService.renew(
                self.cred.id,
                {"tenant_id": 2, "issuer_name": "Replacement issuer"},
                tenant_id=1,
            )

        self.assertIn("tenant_id", str(caught.exception))
        self.cred.refresh_from_db()
        self.assertEqual(self.cred.tenant_id, 1)
        self.assertEqual(self.cred.status, CredentialStatus.ACTIVE)


class ApplicationServiceTest(TestCase):
    def setUp(self):
        self.person = HrPerson.objects.create(tenant_id=1, legal_name="双师申请测试人员")
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
            person_id=self.person,
            application_no="APP-TEST-001",
            batch_id=self.batch,
            target_level=RecognitionLevel.DOUBLE_TEACHER_JUNIOR,
            status=ApplicationStatus.DRAFT,
        )

    def test_submit_from_draft_requires_dedicated_gate(self):
        with self.assertRaises(ApplicationError) as cm:
            ApplicationService.transition(self.app, ApplicationStatus.SUBMITTED)
        self.assertEqual(cm.exception.code, "APPLICATION_GUARDED_TRANSITION")
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, ApplicationStatus.DRAFT)

    def test_cannot_jump_to_final(self):
        with self.assertRaises(ApplicationError):
            ApplicationService.transition(self.app, ApplicationStatus.RECOGNIZED)

    def test_withdraw(self):
        # Submission itself is covered by the dedicated lifecycle-gate suite.
        # This fixture starts from an already-submitted fact so this unit test
        # remains focused on the SUBMITTED -> WITHDRAWN state transition.
        self.app.status = ApplicationStatus.SUBMITTED
        self.app.save(update_fields=["status", "updated_at"])
        app = ApplicationService.transition(self.app, ApplicationStatus.WITHDRAWN)
        self.assertEqual(app.status, ApplicationStatus.WITHDRAWN)

    def test_guarded_submit_does_not_set_timestamp(self):
        with self.assertRaises(ApplicationError):
            ApplicationService.transition(self.app, ApplicationStatus.SUBMITTED)
        self.app.refresh_from_db()
        self.assertIsNone(self.app.submitted_at)


class RiskServiceTest(TestCase):
    def setUp(self):
        self.person = HrPerson.objects.create(tenant_id=1, legal_name="风险测试人员")
        self.catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=None, code="TEST-RISK", category="OTHER", name="Risk Cert"
        )

    def test_dedup_risk(self):
        """同类型 OPEN 风险不重复创建"""
        cred = HrPersonCredential.objects.create(
            tenant_id=1,
            person_id=self.person,
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
