from datetime import date

from django.test import TestCase, override_settings

from hr_data.models import DataQualityRuleVersion, DataQualityRun
from hr_data.providers.hr03_quality import quality_provider
from hr_data.services.quality_runtime_service import RuntimeDataQualityExecutionService
from hr_staff.models import (
    HrEmploymentRelationship,
    HrPerson,
    HrStaffAssignment,
    HrStaffMaster,
)


OVERRIDE_CALLS = []


def override_provider(**kwargs):
    OVERRIDE_CALLS.append(kwargs)
    return {
        "status": "OK",
        "providerVersion": "override-v1",
        "evidenceHash": "f" * 64,
        "findings": [],
    }


class Hr03BuiltinQualityProviderTests(TestCase):
    def _staff(self, no):
        person = HrPerson.objects.create(tenant_id=77, legal_name=f"教师-{no}")
        return HrStaffMaster.objects.create(
            tenant_id=77,
            person_id=person,
            staff_no=no,
            current_employment_status="ACTIVE",
        )

    def _relationship(self, staff, *, source_type="TEST", source_id="REL-1"):
        return HrEmploymentRelationship.objects.create(
            tenant_id=77,
            staff_id=staff,
            employment_type="FULL_TIME",
            effective_from=date(2025, 1, 1),
            status="ACTIVE",
            source_business_type=source_type,
            source_business_id=source_id,
        )

    def _assignment(
        self,
        relationship,
        *,
        source_type="TEST",
        source_id="ASSIGN-1",
    ):
        return HrStaffAssignment.objects.create(
            tenant_id=77,
            employment_relationship_id=relationship,
            assignment_type="PRIMARY",
            assignment_role_code="TEACHER",
            effective_from=date(2025, 1, 1),
            status="ACTIVE",
            source_business_type=source_type,
            source_business_id=source_id,
        )

    def test_employment_provenance_finds_missing_source_and_is_deterministic(self):
        self._relationship(self._staff("T001"), source_type="", source_id="")

        first = quality_provider(
            tenant_id=77,
            source_domain="HR03",
            rule_code="HR03_EMPLOYMENT_PROVENANCE_REQUIRED",
            rule_version=1,
            rule_parameters={},
            as_of_date=date(2026, 8, 1),
        )
        second = quality_provider(
            tenant_id=77,
            source_domain="HR03",
            rule_code="HR03_EMPLOYMENT_PROVENANCE_REQUIRED",
            rule_version=1,
            rule_parameters={},
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(first["status"], "OK")
        self.assertEqual(first["evidenceHash"], second["evidenceHash"])
        self.assertEqual(len(first["findings"]), 1)
        finding = first["findings"][0]
        self.assertEqual(len(finding["fingerprint"]), 64)
        self.assertEqual(
            finding["details"]["missingFields"],
            ["sourceBusinessType", "sourceBusinessId"],
        )

    def test_clean_provenance_has_no_findings(self):
        relationship = self._relationship(self._staff("T002"))
        self._assignment(relationship)

        employment = quality_provider(
            tenant_id=77,
            source_domain="HR03",
            rule_code="HR03_EMPLOYMENT_PROVENANCE_REQUIRED",
            rule_version=1,
            rule_parameters={},
            as_of_date=date(2026, 8, 1),
        )
        assignment = quality_provider(
            tenant_id=77,
            source_domain="HR03",
            rule_code="HR03_ASSIGNMENT_PROVENANCE_REQUIRED",
            rule_version=1,
            rule_parameters={},
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(employment["status"], "OK")
        self.assertEqual(employment["findings"], [])
        self.assertEqual(assignment["status"], "OK")
        self.assertEqual(assignment["findings"], [])

    def test_assignment_authority_link_rule_flags_missing_hr02_links(self):
        relationship = self._relationship(self._staff("T003"))
        self._assignment(relationship)

        receipt = quality_provider(
            tenant_id=77,
            source_domain="HR03",
            rule_code="HR03_ASSIGNMENT_AUTHORITY_LINK_REQUIRED",
            rule_version=1,
            rule_parameters={
                "requireOrganization": True,
                "requirePosition": True,
                "requirePostCatalog": False,
            },
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(receipt["status"], "OK")
        self.assertEqual(len(receipt["findings"]), 1)
        self.assertEqual(
            receipt["findings"][0]["details"]["missingAuthorityLinks"],
            ["organizationId", "positionId"],
        )

    def test_ended_rows_are_scoped_by_requested_asof_date(self):
        relationship = self._relationship(
            self._staff("T004"),
            source_type="",
            source_id="",
        )
        relationship.effective_to = date(2026, 7, 1)
        relationship.save(update_fields=["effective_to", "updated_at"])

        historical = quality_provider(
            tenant_id=77,
            source_domain="HR03",
            rule_code="HR03_EMPLOYMENT_PROVENANCE_REQUIRED",
            rule_version=1,
            rule_parameters={},
            as_of_date=date(2026, 6, 1),
        )
        current = quality_provider(
            tenant_id=77,
            source_domain="HR03",
            rule_code="HR03_EMPLOYMENT_PROVENANCE_REQUIRED",
            rule_version=1,
            rule_parameters={},
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(len(historical["findings"]), 1)
        self.assertEqual(current["findings"], [])

    def test_unknown_rule_and_invalid_parameters_fail_closed(self):
        unknown = quality_provider(
            tenant_id=77,
            source_domain="HR03",
            rule_code="SCHOOL_SPECIFIC_UNKNOWN_RULE",
            rule_version=1,
            rule_parameters={},
            as_of_date=date(2026, 8, 1),
        )
        invalid = quality_provider(
            tenant_id=77,
            source_domain="HR03",
            rule_code="HR03_ASSIGNMENT_AUTHORITY_LINK_REQUIRED",
            rule_version=1,
            rule_parameters={"inventedPolicy": True},
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(unknown["status"], "UNAVAILABLE")
        self.assertEqual(invalid["status"], "ERROR")


class RuntimeDataQualityExecutionTests(TestCase):
    def setUp(self):
        OVERRIDE_CALLS.clear()

    def _rule(self, code="HR03_EMPLOYMENT_PROVENANCE_REQUIRED"):
        return DataQualityRuleVersion.objects.create(
            tenant_id=77,
            rule_code=code,
            name=code,
            source_domain="HR03",
            severity="ERROR",
            parameters_json={},
            version_no=1,
            content_hash="a" * 64,
        )

    def test_runtime_has_builtin_hr03_provider_without_settings(self):
        self._rule()
        outcome = RuntimeDataQualityExecutionService(77).execute(
            run_no="QRUN-BUILTIN-HR03",
            rule_code="HR03_EMPLOYMENT_PROVENANCE_REQUIRED",
            rule_version=1,
            as_of_date=date(2026, 8, 1),
        )
        self.assertEqual(outcome.run.status, DataQualityRun.Status.SUCCESS)
        self.assertEqual(outcome.run.provider_version, "hr03-quality-core-v1")
        self.assertEqual(len(outcome.run.evidence_hash), 64)

    @override_settings(
        HR18_QUALITY_PROVIDERS={
            "HR03": "hr_data.tests.test_hr03_quality_runtime.override_provider"
        }
    )
    def test_configured_provider_overrides_builtin(self):
        self._rule()
        outcome = RuntimeDataQualityExecutionService(77, actor_user_id=9).execute(
            run_no="QRUN-OVERRIDE-HR03",
            rule_code="HR03_EMPLOYMENT_PROVENANCE_REQUIRED",
            rule_version=1,
            as_of_date=date(2026, 8, 1),
        )
        self.assertEqual(outcome.run.status, DataQualityRun.Status.SUCCESS)
        self.assertEqual(outcome.run.provider_version, "override-v1")
        self.assertEqual(len(OVERRIDE_CALLS), 1)
        self.assertEqual(OVERRIDE_CALLS[0]["tenant_id"], 77)
        self.assertEqual(OVERRIDE_CALLS[0]["actor_user_id"], 9)
