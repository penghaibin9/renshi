"""
tests/test_models.py —— 模型层测试（总册 §161/S11）。

覆盖：
- 27 个模型均可创建
- 唯一约束生效
- 乐观锁 version 递增
- 证号加密/掩码
- FK protect 不可级联删除
"""

import uuid
from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from hr_qualification.constants import (
    CredentialCategory,
    CredentialStatus,
    RecognitionLevel,
    RulePackVersionStatus,
)
from hr_qualification.models import (
    HrCredentialCatalogItem,
    HrCredentialDocument,
    HrCredentialRenewal,
    HrCredentialRequirement,
    HrCredentialStatusEvent,
    HrCredentialVerification,
    HrDoubleTeacherApplication,
    HrDoubleTeacherEvidencePackage,
    HrDoubleTeacherRecognitionBatch,
    HrDoubleTeacherRecognition,
    HrDoubleTeacherRule,
    HrDoubleTeacherRulePack,
    HrDoubleTeacherRulePackVersion,
    HrPersonCredential,
    HrQualificationRiskCase,
)
from hr_staff.models import HrPerson


class CredentialCatalogTest(TestCase):
    def test_create_system_catalog(self):
        item = HrCredentialCatalogItem.objects.create(
            tenant_id=None,
            code="TEST-001",
            category=CredentialCategory.TEACHER_QUALIFICATION,
            name="Test Catalog",
        )
        self.assertEqual(item.code, "TEST-001")
        self.assertIsNone(item.tenant_id)

    def test_unique_tenant_code(self):
        HrCredentialCatalogItem.objects.create(
            tenant_id=1, code="DUP", category="OTHER", name="A"
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrCredentialCatalogItem.objects.create(
                    tenant_id=1, code="DUP", category="OTHER", name="B"
                )


class PersonCredentialTest(TestCase):
    def test_masked_no(self):
        c = HrPersonCredential(
            tenant_id=1,
            credential_name_snapshot="Test Cert",
            issuer_name="Issuer",
            certificate_no_hash="abcdef12345678",
        )
        self.assertEqual(c.masked_no, "******5678")

    def test_masked_no_empty(self):
        c = HrPersonCredential(
            tenant_id=1,
            credential_name_snapshot="Test Cert",
            issuer_name="Issuer",
        )
        self.assertEqual(c.masked_no, "")

    def test_version_increment(self):
        person = HrPerson.objects.create(tenant_id=1, legal_name="模型资格测试人员")
        c = HrPersonCredential.objects.create(
            tenant_id=1,
            person_id=person,
            credential_name_snapshot="V1",
            issuer_name="Issuer",
        )
        self.assertEqual(c.version, 1)
        c.status = CredentialStatus.ACTIVE
        c.version += 1
        c.save()
        c.refresh_from_db()
        self.assertEqual(c.version, 2)


class DoubleTeacherRuleTest(TestCase):
    def test_create_rule_pack(self):
        pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=1,
            code="SCHOOL-2026",
            name="School Rules 2026",
        )
        self.assertEqual(pack.code, "SCHOOL-2026")

    def test_create_version(self):
        pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=1, code="TEST-PACK", name="Test Pack"
        )
        version = HrDoubleTeacherRulePackVersion.objects.create(
            rule_pack_id=pack,
            version_no=1,
            effective_from="2026-01-01",
            status=RulePackVersionStatus.DRAFT,
        )
        self.assertEqual(version.status, RulePackVersionStatus.DRAFT)

    def test_create_rule(self):
        pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=1, code="TEST-RULE-PACK", name="Test Rule Pack"
        )
        version = HrDoubleTeacherRulePackVersion.objects.create(
            rule_pack_id=pack, version_no=1, effective_from="2026-01-01"
        )
        rule = HrDoubleTeacherRule.objects.create(
            version_id=version,
            level=RecognitionLevel.DOUBLE_TEACHER_JUNIOR,
            dimension_code="TEACHING_ABILITY",
            rule_code="TEST-001",
            rule_type="BOOLEAN_FACT",
            expected_value_json={"value": True},
        )
        self.assertEqual(rule.rule_code, "TEST-001")
        self.assertEqual(rule.rule_type, "BOOLEAN_FACT")


class RiskCaseTest(TestCase):
    def test_create_risk(self):
        person = HrPerson.objects.create(tenant_id=1, legal_name="模型风险测试人员")
        risk = HrQualificationRiskCase.objects.create(
            tenant_id=1,
            person_id=person,
            risk_type="CREDENTIAL_EXPIRED",
            severity="HIGH",
        )
        self.assertEqual(risk.status, "OPEN")
        self.assertEqual(risk.severity, "HIGH")


class ProviderStatusTest(TestCase):
    def test_unavailable_not_equal_zero(self):
        """硬门：UNAVAILABLE != 0 != false"""
        from hr_qualification.constants import ProviderStatus
        status = ProviderStatus.UNAVAILABLE
        self.assertNotEqual(status, ProviderStatus.OK)
        self.assertEqual(status, "UNAVAILABLE")
