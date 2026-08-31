import json
from datetime import date

from django.test import TestCase, override_settings

from hr_data.models import AsOfEvidenceSnapshot, MetricDefinitionVersion, PopulationDefinitionVersion
from hr_data.providers.hr03 import PROVIDER_VERSION, asof_provider
from hr_data.services.asof_service import AsOfReconstructionService
from hr_staff.models import HrEmploymentRelationship, HrPerson, HrStaffAssignment, HrStaffMaster


class Hr03AsOfProviderTests(TestCase):
    def _staff(self, *, tenant_id=77, staff_no="T001", current_status="ACTIVE"):
        person = HrPerson.objects.create(
            tenant_id=tenant_id,
            legal_name=f"教师-{staff_no}",
        )
        return HrStaffMaster.objects.create(
            tenant_id=tenant_id,
            person_id=person,
            staff_no=staff_no,
            current_employment_status=current_status,
        )

    def _relationship(
        self,
        staff,
        *,
        effective_from=date(2025, 1, 1),
        effective_to=None,
        status="ACTIVE",
    ):
        return HrEmploymentRelationship.objects.create(
            tenant_id=staff.tenant_id,
            staff_id=staff,
            effective_from=effective_from,
            effective_to=effective_to,
            status=status,
            source_business_type="TEST",
            source_business_id=f"REL-{staff.staff_no}",
        )

    def _population(self, *, code, field, tenant_id=77, sources=None):
        return PopulationDefinitionVersion.objects.create(
            tenant_id=tenant_id,
            population_code=code,
            name=code,
            root_domain="HR03",
            predicate_json={"field": field, "op": "eq", "value": "ACTIVE"},
            source_domains=sources or ["HR03"],
            version_no=1,
            content_hash="a" * 64,
        )

    def test_builtin_provider_completes_supported_hr03_population(self):
        staff = self._staff()
        self._relationship(staff)
        population = self._population(code="ACTIVE_STAFF", field="employment.status")

        outcome = AsOfReconstructionService(77).reconstruct(
            evidence_no="HR03-E-001",
            definition_kind="POPULATION",
            definition_code=population.population_code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(outcome.evidence.status, AsOfEvidenceSnapshot.Status.COMPLETE)
        self.assertEqual(outcome.evidence.source_statuses_json, {"HR03": "OK"})
        self.assertEqual(outcome.evidence.provider_versions_json["HR03"], PROVIDER_VERSION)
        self.assertEqual(len(outcome.evidence.provider_evidence_hashes_json["HR03"]), 64)

    def test_current_projection_change_does_not_change_historical_provider_hash(self):
        staff = self._staff(current_status="ACTIVE")
        self._relationship(staff)
        population = self._population(code="REL_STATUS", field="employment.status")

        first = asof_provider(
            tenant_id=77,
            source_domain="HR03",
            definition_kind="POPULATION",
            definition_code=population.population_code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )
        staff.current_employment_status = "DEPARTED"
        staff.save(update_fields=["current_employment_status", "updated_at"])
        second = asof_provider(
            tenant_id=77,
            source_domain="HR03",
            definition_kind="POPULATION",
            definition_code=population.population_code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(first["status"], "OK")
        self.assertEqual(second["status"], "OK")
        self.assertEqual(first["evidenceHash"], second["evidenceHash"])

    def test_authoritative_segment_change_changes_hash_but_foreign_tenant_does_not(self):
        staff = self._staff()
        self._relationship(staff)
        population = self._population(code="REL_HASH", field="employment.status")
        first = asof_provider(
            tenant_id=77,
            source_domain="HR03",
            definition_kind="POPULATION",
            definition_code=population.population_code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )["evidenceHash"]

        foreign = self._staff(tenant_id=88, staff_no="F001")
        self._relationship(foreign)
        after_foreign = asof_provider(
            tenant_id=77,
            source_domain="HR03",
            definition_kind="POPULATION",
            definition_code=population.population_code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )["evidenceHash"]
        self.assertEqual(first, after_foreign)

        second_staff = self._staff(staff_no="T002")
        self._relationship(second_staff)
        after_local = asof_provider(
            tenant_id=77,
            source_domain="HR03",
            definition_kind="POPULATION",
            definition_code=population.population_code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )["evidenceHash"]
        self.assertNotEqual(first, after_local)

    def test_unsupported_current_projection_field_fails_closed(self):
        staff = self._staff()
        self._relationship(staff)
        population = self._population(
            code="BAD_CURRENT_STATUS",
            field="staff.current_employment_status",
        )

        receipt = asof_provider(
            tenant_id=77,
            source_domain="HR03",
            definition_kind="POPULATION",
            definition_code=population.population_code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(receipt["status"], "UNAVAILABLE")
        self.assertEqual(receipt["evidenceHash"], "")

    def test_assignment_fact_is_supported_without_current_staff_projection(self):
        staff = self._staff()
        relationship = self._relationship(staff)
        HrStaffAssignment.objects.create(
            tenant_id=77,
            employment_relationship_id=relationship,
            assignment_type="PRIMARY",
            assignment_role_code="TEACHER",
            effective_from=date(2025, 1, 1),
            status="ACTIVE",
        )
        population = self._population(
            code="PRIMARY_ASSIGNMENT",
            field="assignment.assignmentType",
        )

        receipt = asof_provider(
            tenant_id=77,
            source_domain="HR03",
            definition_kind="POPULATION",
            definition_code=population.population_code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(receipt["status"], "OK")
        self.assertEqual(len(receipt["evidenceHash"]), 64)

    def test_multidomain_metric_does_not_make_hr03_claim_payroll_field(self):
        staff = self._staff()
        self._relationship(staff)
        population = self._population(
            code="PAYROLL_POP",
            field="employment.status",
            sources=["HR03", "HR15"],
        )
        MetricDefinitionVersion.objects.create(
            tenant_id=77,
            metric_code="TOTAL_GROSS_PAY",
            name="应发合计",
            value_type="DECIMAL",
            unit="CNY",
            population_code=population.population_code,
            expression=json.dumps(
                {
                    "dslVersion": "1",
                    "populationVersion": 1,
                    "op": "SUM",
                    "field": "payroll.grossAmount",
                }
            ),
            source_domains=["HR03", "HR15"],
            version_no=1,
            content_hash="b" * 64,
        )

        receipt = asof_provider(
            tenant_id=77,
            source_domain="HR03",
            definition_kind="METRIC",
            definition_code="TOTAL_GROSS_PAY",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(receipt["status"], "OK")
        self.assertEqual(len(receipt["evidenceHash"]), 64)

    @override_settings(HR18_ASOF_PROVIDERS={"HR03": ""})
    def test_deployment_can_explicitly_disable_builtin_hr03_provider(self):
        staff = self._staff()
        self._relationship(staff)
        population = self._population(code="DISABLED_HR03", field="employment.status")

        outcome = AsOfReconstructionService(77).reconstruct(
            evidence_no="HR03-DISABLED",
            definition_kind="POPULATION",
            definition_code=population.population_code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(outcome.evidence.status, AsOfEvidenceSnapshot.Status.UNAVAILABLE)
        self.assertEqual(outcome.evidence.source_statuses_json["HR03"], "UNAVAILABLE")
