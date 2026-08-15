from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from hr_self.services.identity_service import SelfIdentityContext
from hr_self.services.provider_gateway import (
    ProviderStatus,
    SelfProviderResult,
    default_self_provider_registry,
    hr07_self_provider,
    hr14_self_provider,
    hr16_self_provider,
)


class Hr17CanonicalAuthorityProviderTests(SimpleTestCase):
    def setUp(self):
        self.context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id="00000000-0000-0000-0000-000000000301",
            person_id="00000000-0000-0000-0000-000000000201",
            legacy_employee_id=51,
        )
        self.updated_at = datetime(2026, 8, 15, 1, 2, 3, tzinfo=timezone.utc)

    @staticmethod
    def _rows(model, rows):
        model.objects.filter.return_value.order_by.return_value.__getitem__.return_value = rows

    @patch("hr_contracts.models.HrContractAgreement")
    def test_hr07_reads_only_tenant_scoped_self_contract_metadata(self, agreement_model):
        agreement = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000701",
            agreement_no="HT-2026-001",
            employment_relationship_id="00000000-0000-0000-0000-000000000702",
            agreement_title="教师聘用合同",
            agreement_type="EMPLOYMENT",
            status="ACTIVE",
            current_version_no=3,
            updated_at=self.updated_at,
        )
        self._rows(agreement_model, [agreement])

        result = hr07_self_provider(self.context)

        self.assertEqual(result.status, ProviderStatus.OK)
        agreement_model.objects.filter.assert_called_once_with(
            tenant_id=77,
            staff_id=self.context.staff_id,
        )
        self.assertEqual(result.data["contractAgreements"][0]["agreementNo"], "HT-2026-001")
        self.assertEqual(result.data["contractAgreements"][0]["status"], "ACTIVE")
        self.assertNotIn("contentSnapshot", result.data["contractAgreements"][0])
        self.assertNotIn("signedDocumentRef", result.data["contractAgreements"][0])
        self.assertEqual(result.meta["authority"], "HR07_CONTRACT_AUTHORITY")
        self.assertEqual(result.source_updated_at, self.updated_at)

    @patch("hr_appointment.models.PositionAppointmentFact")
    @patch("hr_appointment.models.AppointmentApplicationCase")
    def test_hr14_returns_history_without_guessing_one_current_record(
        self,
        application_model,
        fact_model,
    ):
        application = SimpleNamespace(
            id="00000000-0000-0000-0000-000000001401",
            case_no="AP-2026-001",
            policy_version_id="00000000-0000-0000-0000-000000001402",
            position_instance_id=14001,
            batch_no="BATCH-2026-A",
            requested_level_code="L2",
            status="PUBLICITY",
            updated_at=self.updated_at,
        )
        fact = SimpleNamespace(
            id="00000000-0000-0000-0000-000000001403",
            appointment_no="APT-2026-001",
            position_instance_id=14001,
            application_case_id=application.id,
            level_code="L2",
            effective_from=date(2026, 9, 1),
            effective_to=None,
            status="EFFECTIVE",
            supersedes_fact_id=None,
            created_at=self.updated_at,
            updated_at=self.updated_at,
        )
        self._rows(application_model, [application])
        self._rows(fact_model, [fact])

        result = hr14_self_provider(self.context)

        self.assertEqual(result.status, ProviderStatus.OK)
        application_model.objects.filter.assert_called_once_with(
            tenant_id=77,
            person_id=self.context.person_id,
        )
        fact_model.objects.filter.assert_called_once_with(
            tenant_id=77,
            person_id=self.context.person_id,
        )
        self.assertEqual(result.data["appointmentApplications"][0]["status"], "PUBLICITY")
        self.assertEqual(result.data["appointmentFacts"][0]["status"], "EFFECTIVE")
        self.assertEqual(result.data["appointmentFacts"][0]["effectiveFrom"], "2026-09-01")
        self.assertEqual(result.meta["authority"], "HR14_APPOINTMENT_AUTHORITY")

    def test_hr16_reads_self_exit_and_retirement_facts_without_effect_receipts(self):
        exit_case = SimpleNamespace(
            id="00000000-0000-0000-0000-000000001601",
            case_no="EXIT-2026-001",
            employment_relationship_id="00000000-0000-0000-0000-000000001602",
            exit_type="RETIREMENT",
            status="HANDOVER",
            requested_date=date(2026, 6, 1),
            last_working_date=date(2026, 8, 31),
            planned_employment_end_date=date(2026, 8, 31),
            planned_access_end_at=self.updated_at,
            updated_at=self.updated_at,
        )
        exit_fact = SimpleNamespace(
            id="00000000-0000-0000-0000-000000001603",
            fact_no="EXIT-F-2026-001",
            employment_relationship_id=exit_case.employment_relationship_id,
            source_case_id=exit_case.id,
            exit_type="RETIREMENT",
            employment_end_date=date(2026, 8, 31),
            last_working_date=date(2026, 8, 31),
            access_end_at=self.updated_at,
            status="EFFECTIVE",
            supersedes_fact_id=None,
            created_at=self.updated_at,
            updated_at=self.updated_at,
        )
        retirement = SimpleNamespace(
            id="00000000-0000-0000-0000-000000001604",
            fact_no="RET-2026-001",
            exit_fact_id=exit_fact.id,
            retirement_type="STATUTORY",
            statutory_date=date(2026, 8, 31),
            effective_date=date(2026, 9, 1),
            pension_processing_status="IN_PROGRESS",
            status="EFFECTIVE",
            supersedes_fact_id=None,
            created_at=self.updated_at,
            updated_at=self.updated_at,
        )

        with (
            patch("hr_exit.models.ExitCase") as exit_case_model,
            patch("hr_exit.models.ExitFact") as exit_fact_model,
            patch("hr_exit.models.RetirementFact") as retirement_model,
        ):
            self._rows(exit_case_model, [exit_case])
            self._rows(exit_fact_model, [exit_fact])
            self._rows(retirement_model, [retirement])

            result = hr16_self_provider(self.context)

        self.assertEqual(result.status, ProviderStatus.OK)
        for model in (exit_case_model, exit_fact_model, retirement_model):
            model.objects.filter.assert_called_once_with(
                tenant_id=77,
                person_id=self.context.person_id,
            )
        self.assertEqual(result.data["exitCases"][0]["status"], "HANDOVER")
        self.assertEqual(result.data["exitFacts"][0]["status"], "EFFECTIVE")
        self.assertEqual(
            result.data["retirementFacts"][0]["pensionProcessingStatus"],
            "IN_PROGRESS",
        )
        self.assertNotIn("effectReceipt", result.data["exitFacts"][0])
        self.assertNotIn("lastEffectError", result.data["exitFacts"][0])
        self.assertEqual(result.meta["authority"], "HR16_EXIT_AUTHORITY")

    def test_default_registry_pins_stable_authority_adapters(self):
        registry = default_self_provider_registry()
        registered = set(registry.registered_domains())
        self.assertTrue({"HR03", "HR07", "HR14", "HR16"}.issubset(registered))

    @override_settings(HR17_SELF_PROVIDER_PATHS={"HR07": "missing.module.legacy_provider"})
    @patch("hr_self.services.provider_gateway.hr07_self_provider")
    def test_runtime_configuration_cannot_shadow_canonical_hr07(self, canonical_provider):
        canonical_provider.return_value = SelfProviderResult.ok(
            {"source": "canonical-HR07"},
            provider_version="canonical-test",
        )

        registry = default_self_provider_registry()
        result = registry.call("HR07", self.context)

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data["source"], "canonical-HR07")
        self.assertEqual(result.provider_version, "canonical-test")
