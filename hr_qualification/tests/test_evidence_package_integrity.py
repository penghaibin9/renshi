"""Evidence package snapshot and checksum integrity contracts."""

import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase

from hr_qualification.constants import (
    HardOrSoft,
    JurisdictionLevel,
    RecognitionLevel,
    RuleType,
)
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherEvidenceItem,
    HrDoubleTeacherEvidencePackage,
    HrDoubleTeacherRecognitionBatch,
    HrDoubleTeacherRule,
    HrDoubleTeacherRulePack,
    HrDoubleTeacherRulePackVersion,
)
from hr_qualification.services.evidence_service import (
    EvidenceAggregationError,
    EvidenceAggregationService,
)
from hr_qualification.services.rule_service import RuleService
from hr_staff.models import HrPerson, HrStaffMaster


class EvidencePackageIntegrityTests(TestCase):
    def setUp(self):
        self.tenant_id = 85123
        person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="Evidence checksum",
        )
        staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=person,
            staff_no=f"EVID-{uuid.uuid4().hex}",
        )
        pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=self.tenant_id,
            jurisdiction_level=JurisdictionLevel.SCHOOL,
            jurisdiction_code="TEST",
            code=f"PACK-{uuid.uuid4().hex}",
            name="Integrity pack",
        )
        version = HrDoubleTeacherRulePackVersion.objects.create(
            rule_pack_id=pack,
            version_no=1,
            effective_from=date(2026, 1, 1),
        )
        HrDoubleTeacherRule.objects.create(
            version_id=version,
            rule_code=f"RULE-{uuid.uuid4().hex}",
            dimension_code="TEACHING_ABILITY",
            level=RecognitionLevel.DOUBLE_TEACHER_JUNIOR,
            rule_type=RuleType.BOOLEAN_FACT,
            expected_value_json={"value": True},
            operator=">=",
            hard_or_soft=HardOrSoft.HARD,
            source_provider="HR09_CREDENTIAL",
            sequence=10,
        )
        version = RuleService.publish(version)
        batch = HrDoubleTeacherRecognitionBatch.objects.create(
            tenant_id=self.tenant_id,
            batch_no=f"BATCH-{uuid.uuid4().hex}",
            name="Integrity batch",
            rule_pack_version_id=version,
        )
        application = HrDoubleTeacherApplication.objects.create(
            tenant_id=self.tenant_id,
            application_no=f"APP-{uuid.uuid4().hex}",
            batch_id=batch,
            person_id=person,
            staff_master_id=staff,
            target_level=RecognitionLevel.DOUBLE_TEACHER_JUNIOR,
        )
        self.package = HrDoubleTeacherEvidencePackage.objects.create(
            application_id=application,
            rule_pack_version_id=version,
            source_snapshots_json={
                "_meta": {"asOf": "2026-08-01", "providerCount": 1},
                "HR09_CREDENTIAL": {
                    "status": "OK",
                    "itemsCount": 1,
                    "providerVersion": "hr09-credential-evidence-v1",
                    "sourceUpdatedAt": "2026-07-01T00:00:00+00:00",
                    "errors": [],
                },
            },
        )
        self.item = HrDoubleTeacherEvidenceItem.objects.create(
            package_id=self.package,
            source_domain="HR09_CREDENTIAL",
            source_object_type="HrPersonCredential",
            source_object_id=str(uuid.uuid4()),
            evidence_date=date(2026, 7, 1),
            title="Credential",
            role="VOCATIONAL_QUALIFICATION",
            quantitative_value=Decimal("4"),
            verification_status="VERIFIED",
            document_refs=["file-1"],
            snapshot_json={"level_rank": 4, "status": "ACTIVE"},
        )
        self.package.checksum = EvidenceAggregationService.compute_package_checksum(
            self.package
        )
        self.package.save(update_fields=["checksum"])

    def test_quantitative_tamper_changes_checksum_and_blocks_freeze(self):
        original = self.package.checksum
        self.item.quantitative_value = Decimal("5")
        self.item.save(update_fields=["quantitative_value"])

        self.assertNotEqual(
            EvidenceAggregationService.compute_package_checksum(self.package),
            original,
        )
        with self.assertRaises(EvidenceAggregationError) as cm:
            EvidenceAggregationService.freeze_package(self.package)
        self.assertEqual(cm.exception.code, "EVIDENCE_PACKAGE_CHECKSUM_MISMATCH")

    def test_snapshot_tamper_changes_checksum(self):
        original = self.package.checksum
        self.item.snapshot_json = {"level_rank": 99, "status": "ACTIVE"}
        self.item.save(update_fields=["snapshot_json"])
        self.assertNotEqual(
            EvidenceAggregationService.compute_package_checksum(self.package),
            original,
        )
