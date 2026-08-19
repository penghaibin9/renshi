"""Application lifecycle hard gates: precheck cannot be bypassed."""

import uuid
from datetime import date

from django.test import TestCase

from hr_qualification.constants import (
    ApplicationStatus,
    EvidencePackageStatus,
    HardOrSoft,
    JurisdictionLevel,
    PrecheckResultType,
    RecognitionLevel,
    RuleType,
)
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherEvidenceItem,
    HrDoubleTeacherEvidencePackage,
    HrDoubleTeacherEvidenceRequirement,
    HrDoubleTeacherRecognitionBatch,
    HrDoubleTeacherRule,
    HrDoubleTeacherRulePack,
    HrDoubleTeacherRulePackVersion,
)
from hr_qualification.services.application_service import ApplicationError, ApplicationService
from hr_qualification.services.evidence_service import EvidenceAggregationService
from hr_qualification.services.precheck_service import PrecheckResult
from hr_staff.models import HrPerson, HrStaffMaster


class ApplicationLifecycleGateTests(TestCase):
    def setUp(self):
        self.tenant_id = 86123
        person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="Lifecycle gate",
        )
        staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=person,
            staff_no=f"APP-GATE-{uuid.uuid4().hex}",
        )
        pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=self.tenant_id,
            jurisdiction_level=JurisdictionLevel.SCHOOL,
            jurisdiction_code="TEST",
            code=f"APP-GATE-{uuid.uuid4().hex}",
            name="Application gate pack",
        )
        self.version = HrDoubleTeacherRulePackVersion.objects.create(
            rule_pack_id=pack,
            version_no=1,
            effective_from=date(2026, 1, 1),
        )
        batch = HrDoubleTeacherRecognitionBatch.objects.create(
            tenant_id=self.tenant_id,
            batch_no=f"APP-GATE-B-{uuid.uuid4().hex}",
            name="Application gate batch",
            rule_pack_version_id=self.version,
        )
        self.application = HrDoubleTeacherApplication.objects.create(
            tenant_id=self.tenant_id,
            application_no=f"APP-GATE-A-{uuid.uuid4().hex}",
            batch_id=batch,
            person_id=person,
            staff_master_id=staff,
            target_level=RecognitionLevel.DOUBLE_TEACHER_JUNIOR,
        )
        self.rule = HrDoubleTeacherRule.objects.create(
            version_id=self.version,
            rule_code=f"RULE-{uuid.uuid4().hex}",
            dimension_code="QUALIFICATION",
            level=RecognitionLevel.DOUBLE_TEACHER_JUNIOR,
            rule_type=RuleType.BOOLEAN_FACT,
            expected_value_json={"value": True},
            operator=">=",
            hard_or_soft=HardOrSoft.HARD,
            source_provider="HR09_CREDENTIAL",
            sequence=10,
        )
        self.requirement = HrDoubleTeacherEvidenceRequirement.objects.create(
            rule_id=self.rule,
            evidence_category="HR09_CREDENTIAL",
            min_count=1,
            verification_required=True,
            document_required=False,
        )

    def _generated_passing_package(self):
        package = HrDoubleTeacherEvidencePackage.objects.create(
            application_id=self.application,
            rule_pack_version_id=self.version,
            source_snapshots_json={
                "_meta": {"asOf": "2026-08-19", "providerCount": 1},
                "HR09_CREDENTIAL": {
                    "status": "OK",
                    "itemsCount": 1,
                    "providerVersion": "hr09-credential-evidence-v1",
                    "sourceUpdatedAt": "2026-08-19T01:00:00+00:00",
                    "errors": [],
                },
            },
            status=EvidencePackageStatus.GENERATED,
        )
        item = HrDoubleTeacherEvidenceItem.objects.create(
            package_id=package,
            requirement_id=self.requirement,
            source_domain="HR09_CREDENTIAL",
            source_object_type="HrPersonCredential",
            source_object_id=str(uuid.uuid4()),
            evidence_date=date(2026, 8, 1),
            title="Verified credential",
            role="VOCATIONAL_QUALIFICATION",
            quantitative_value=4,
            verification_status="VERIFIED",
            document_refs=[],
            snapshot_json={"level_rank": 4, "status": "ACTIVE"},
        )
        package.checksum = EvidenceAggregationService.compute_package_checksum(package)
        package.save(update_fields=["checksum"])
        return package, item

    def test_generic_transition_cannot_bypass_ready_or_submitted(self):
        for target in (ApplicationStatus.READY, ApplicationStatus.SUBMITTED):
            with self.assertRaises(ApplicationError) as cm:
                ApplicationService.transition(self.application, target)
            self.assertEqual(cm.exception.code, "APPLICATION_GUARDED_TRANSITION")
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.DRAFT)

    def test_only_passed_precheck_moves_prechecking_to_ready(self):
        app = ApplicationService.start_precheck(self.application)
        result = PrecheckResult(
            application_id=str(app.id),
            overall=PrecheckResultType.PASS,
        )
        app = ApplicationService.complete_precheck(app, result)
        self.assertEqual(app.status, ApplicationStatus.READY)

    def test_failed_precheck_returns_application_to_draft(self):
        app = ApplicationService.start_precheck(self.application)
        result = PrecheckResult(
            application_id=str(app.id),
            overall=PrecheckResultType.MISSING_EVIDENCE,
        )
        app = ApplicationService.complete_precheck(app, result)
        self.assertEqual(app.status, ApplicationStatus.DRAFT)

    def test_submit_rechecks_and_freezes_package_before_status_change(self):
        package, _item = self._generated_passing_package()
        self.application.status = ApplicationStatus.READY
        self.application.save(update_fields=["status", "updated_at"])

        app = ApplicationService.submit(self.application)

        self.assertEqual(app.status, ApplicationStatus.SUBMITTED)
        self.assertIsNotNone(app.submitted_at)
        package.refresh_from_db()
        self.assertEqual(package.status, EvidencePackageStatus.FROZEN)

    def test_tampered_package_blocks_submit_and_keeps_ready(self):
        package, item = self._generated_passing_package()
        self.application.status = ApplicationStatus.READY
        self.application.save(update_fields=["status", "updated_at"])
        item.title = "tampered after precheck"
        item.save(update_fields=["title"])

        with self.assertRaises(ApplicationError) as cm:
            ApplicationService.submit(self.application)

        self.assertEqual(cm.exception.code, "EVIDENCE_PACKAGE_CHECKSUM_MISMATCH")
        self.application.refresh_from_db()
        package.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.READY)
        self.assertEqual(package.status, EvidencePackageStatus.GENERATED)
