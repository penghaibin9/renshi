"""Formal rule authority checksum and typed publish contracts."""

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from hr_qualification.constants import (
    HardOrSoft,
    JurisdictionLevel,
    RecognitionLevel,
    RulePackVersionStatus,
    RuleType,
)
from hr_qualification.models import (
    HrDoubleTeacherEvidenceRequirement,
    HrDoubleTeacherRule,
    HrDoubleTeacherRulePack,
    HrDoubleTeacherRulePackVersion,
)
from hr_qualification.services.rule_service import (
    CHECKSUM_PREFIX,
    RulePackError,
    RuleService,
)


class RuleAuthorityIntegrityTests(TestCase):
    def setUp(self):
        pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=87123,
            jurisdiction_level=JurisdictionLevel.SCHOOL,
            jurisdiction_code="TEST",
            code=f"RULE-INTEGRITY-{uuid.uuid4().hex}",
            name="Rule authority integrity",
        )
        self.version = HrDoubleTeacherRulePackVersion.objects.create(
            rule_pack_id=pack,
            version_no=1,
            effective_from=timezone.localdate() - timedelta(days=1),
            status=RulePackVersionStatus.DRAFT,
            policy_document_ids=["policy-doc-1"],
        )
        self.rule = HrDoubleTeacherRule.objects.create(
            version_id=self.version,
            rule_code="R-BOOL-1",
            dimension_code="TEACHING_ABILITY",
            level=RecognitionLevel.DOUBLE_TEACHER_JUNIOR,
            rule_type=RuleType.BOOLEAN_FACT,
            operator=">=",
            expected_value_json={"value": True},
            hard_or_soft=HardOrSoft.HARD,
            evidence_type="CREDENTIAL",
            source_provider="HR09_CREDENTIAL",
            sequence=10,
        )
        self.requirement = HrDoubleTeacherEvidenceRequirement.objects.create(
            rule_id=self.rule,
            evidence_category="HR09_CREDENTIAL",
            min_count=1,
            allowed_source_domains=["HR09_CREDENTIAL"],
            document_required=True,
            verification_required=True,
        )

    def test_publish_seals_full_v2_payload(self):
        version = RuleService.publish(self.version)
        self.assertEqual(version.status, RulePackVersionStatus.ACTIVE)
        self.assertTrue(version.checksum.startswith(CHECKSUM_PREFIX))
        self.assertIsNotNone(version.published_at)
        RuleService.assert_version_integrity(version)

    def test_operator_drift_after_publish_is_detected(self):
        version = RuleService.publish(self.version)
        self.rule.operator = "<="
        self.rule.save(update_fields=["operator", "updated_at"])
        with self.assertRaises(RulePackError) as cm:
            RuleService.assert_version_integrity(version)
        self.assertEqual(cm.exception.code, "RULE_VERSION_INTEGRITY_DRIFT")

    def test_requirement_drift_after_publish_is_detected(self):
        version = RuleService.publish(self.version)
        self.requirement.document_required = False
        self.requirement.save(update_fields=["document_required"])
        with self.assertRaises(RulePackError) as cm:
            RuleService.assert_version_integrity(version)
        self.assertEqual(cm.exception.code, "RULE_VERSION_INTEGRITY_DRIFT")

    def test_string_level_rule_cannot_publish_as_automated_authority(self):
        self.rule.rule_type = RuleType.LEVEL_AT_LEAST
        self.rule.expected_value_json = {"min_level": "INTERMEDIATE"}
        self.rule.save(update_fields=["rule_type", "expected_value_json", "updated_at"])
        with self.assertRaises(RulePackError) as cm:
            RuleService.publish(self.version)
        self.assertEqual(cm.exception.code, "NORMALIZED_RANK_REQUIRED")
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, RulePackVersionStatus.DRAFT)

    def test_combination_rule_requires_multiple_requirements(self):
        self.rule.rule_type = RuleType.ANY_OF
        self.rule.expected_value_json = {"options": ["A", "B"]}
        self.rule.save(update_fields=["rule_type", "expected_value_json", "updated_at"])
        with self.assertRaises(RulePackError) as cm:
            RuleService.publish(self.version)
        self.assertEqual(cm.exception.code, "COMBINATION_REQUIREMENTS_INSUFFICIENT")

    def test_active_publish_revalidates_integrity_instead_of_silently_returning(self):
        version = RuleService.publish(self.version)
        self.rule.source_provider = "HR03_EDUCATION"
        self.rule.save(update_fields=["source_provider", "updated_at"])
        with self.assertRaises(RulePackError) as cm:
            RuleService.publish(version)
        self.assertEqual(cm.exception.code, "RULE_VERSION_INTEGRITY_DRIFT")
