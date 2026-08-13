from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from hr_data.providers.formal_fact_quality import (
    _hr13_findings,
    _hr14_findings,
    quality_provider,
)
from hr_data.services.quality_runtime_service import RuntimeDataQualityExecutionService


class FormalFactQualityInvariantTests(SimpleTestCase):
    def test_hr13_detects_broken_append_only_chain_and_case_identity(self):
        rows = [
            {
                "id": "r1",
                "person_id": "p1",
                "application_case_id": "c1",
                "status": "EFFECTIVE",
                "effective_from": date(2025, 1, 1),
                "effective_to": None,
                "supersedes_result_id": None,
            },
            {
                "id": "r2",
                "person_id": "p2",
                "application_case_id": "c1",
                "status": "REVISED",
                "effective_from": date(2026, 1, 1),
                "effective_to": None,
                "supersedes_result_id": "r1",
            },
            {
                "id": "r3",
                "person_id": "p1",
                "application_case_id": "c1",
                "status": "REVOKED",
                "effective_from": date(2026, 2, 1),
                "effective_to": None,
                "supersedes_result_id": None,
            },
            {
                "id": "r4",
                "person_id": "p1",
                "application_case_id": "c1",
                "status": "REVISED",
                "effective_from": date(2026, 3, 1),
                "effective_to": None,
                "supersedes_result_id": "r1",
            },
        ]

        findings = _hr13_findings(
            rule_code="HR13_RESULT_CHAIN_INTEGRITY",
            rows=rows,
            cases={"c1": "p1"},
        )
        issues = {item["details"]["issue"] for item in findings}

        self.assertIn("PREDECESSOR_PERSON_MISMATCH", issues)
        self.assertIn("APPLICATION_PERSON_MISMATCH", issues)
        self.assertIn("SUCCESSOR_PREDECESSOR_REQUIRED", issues)
        self.assertIn("MULTIPLE_SUCCESSORS", issues)
        self.assertTrue(all(len(item["fingerprint"]) == 64 for item in findings))

    def test_hr14_terminal_fact_requires_canonical_receipt_but_pending_does_not(self):
        complete_initial_receipt = {
            "hr14PublicityId": "pub-1",
            "hr14QuotaReservationId": "quota-1",
            "hr03AssignmentId": "assign-1",
            "hr03RelationshipId": "rel-1",
            "hr02ReservationId": 10,
            "hr02PositionId": 20,
        }
        rows = [
            {
                "id": "a1",
                "person_id": "p1",
                "application_case_id": "c1",
                "status": "EFFECTIVE",
                "effective_from": date(2025, 1, 1),
                "effective_to": date(2026, 1, 1),
                "effect_receipt_json": complete_initial_receipt,
                "supersedes_fact_id": None,
            },
            {
                "id": "a-pending",
                "person_id": "p1",
                "application_case_id": "c1",
                "status": "EFFECT_PENDING",
                "effective_from": date(2026, 1, 1),
                "effective_to": None,
                "effect_receipt_json": {},
                "supersedes_fact_id": "a1",
            },
            {
                "id": "a2",
                "person_id": "p1",
                "application_case_id": "c1",
                "status": "EFFECTIVE",
                "effective_from": date(2026, 2, 1),
                "effective_to": None,
                "effect_receipt_json": {
                    "sourceFactId": "wrong-source",
                    "hr03Effect": "VERIFIED_UNCHANGED_POSITION",
                },
                "supersedes_fact_id": "a1",
            },
        ]

        findings = _hr14_findings(
            rule_code="HR14_APPOINTMENT_FACT_INTEGRITY",
            rows=rows,
        )
        pending_findings = [
            item for item in findings if item["sourceObjectRef"] == "appointment-fact:a-pending"
        ]
        issues = {item["details"]["issue"] for item in findings}

        self.assertEqual(pending_findings, [])
        self.assertIn("EFFECT_RECEIPT_SOURCE_MISMATCH", issues)
        self.assertIn("SUCCESSOR_EFFECT_RECEIPT_INCOMPLETE", issues)
        self.assertNotIn("EFFECT_RECEIPT_REQUIRED", issues)

    def test_hr14_detects_multiple_terminal_successors(self):
        rows = [
            {
                "id": "a1",
                "person_id": "p1",
                "application_case_id": "c1",
                "status": "EFFECTIVE",
                "effective_from": date(2025, 1, 1),
                "effective_to": date(2026, 1, 1),
                "effect_receipt_json": {
                    "hr14PublicityId": "pub",
                    "hr14QuotaReservationId": "q",
                    "hr03AssignmentId": "a",
                    "hr03RelationshipId": "r",
                    "hr02ReservationId": 1,
                    "hr02PositionId": 2,
                },
                "supersedes_fact_id": None,
            },
        ]
        for idx in (2, 3):
            rows.append(
                {
                    "id": f"a{idx}",
                    "person_id": "p1",
                    "application_case_id": "c1",
                    "status": "EFFECTIVE",
                    "effective_from": date(2026, idx, 1),
                    "effective_to": None,
                    "effect_receipt_json": {
                        "sourceFactId": "a1",
                        "hr14RenewalId": f"renew-{idx}",
                        "hr03AssignmentId": "assign",
                        "hr03Effect": "VERIFIED_UNCHANGED_POSITION",
                    },
                    "supersedes_fact_id": "a1",
                }
            )

        issues = {
            item["details"]["issue"]
            for item in _hr14_findings(
                rule_code="HR14_APPOINTMENT_FACT_INTEGRITY",
                rows=rows,
            )
        }
        self.assertIn("MULTIPLE_TERMINAL_SUCCESSORS", issues)


class FormalFactQualityRuntimeTests(SimpleTestCase):
    def test_missing_sibling_authority_is_unavailable_not_fake_success(self):
        with patch("hr_data.providers.formal_fact_quality._model", return_value=None):
            receipt = quality_provider(
                tenant_id=77,
                source_domain="HR13",
                rule_code="HR13_RESULT_CHAIN_INTEGRITY",
                rule_version=1,
                rule_parameters={},
            )
        self.assertEqual(receipt["status"], "UNAVAILABLE")

    def test_unknown_rule_and_nonempty_parameters_fail_closed(self):
        unknown = quality_provider(
            tenant_id=77,
            source_domain="HR14",
            rule_code="SCHOOL_POLICY_MAGIC",
            rule_version=1,
            rule_parameters={},
        )
        configured_parameters = quality_provider(
            tenant_id=77,
            source_domain="HR14",
            rule_code="HR14_APPOINTMENT_FACT_INTEGRITY",
            rule_version=1,
            rule_parameters={"threshold": 10},
        )
        self.assertEqual(unknown["status"], "UNAVAILABLE")
        self.assertEqual(configured_parameters["status"], "ERROR")

    def test_runtime_registers_formal_providers_and_settings_can_override(self):
        registry = RuntimeDataQualityExecutionService._registry()
        self.assertEqual(
            registry["HR13"],
            "hr_data.providers.formal_fact_quality.quality_provider",
        )
        self.assertEqual(
            registry["HR14"],
            "hr_data.providers.formal_fact_quality.quality_provider",
        )

        with override_settings(HR18_QUALITY_PROVIDERS={"hr13": "custom.provider"}):
            overridden = RuntimeDataQualityExecutionService._registry()
        self.assertEqual(overridden["HR13"], "custom.provider")
        self.assertEqual(
            overridden["HR14"],
            "hr_data.providers.formal_fact_quality.quality_provider",
        )
