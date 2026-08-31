from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from hr_self.services.authority_providers import (
    hr09_self_provider,
    hr10_self_provider,
    hr12_self_provider,
    hr13_self_provider,
    hr15_self_provider,
)
from hr_self.services.identity_service import SelfIdentityContext
from hr_self.services.provider_gateway import (
    ProviderStatus,
    SelfProviderResult,
    default_self_provider_registry,
)


class Hr17StrongAuthorityProviderTests(SimpleTestCase):
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

    @patch("hr_qualification.models.credential.HrPersonCredential")
    def test_hr09_scopes_to_person_and_exposes_only_masked_certificate_number(self, credential_model):
        credential = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000901",
            credential_name_snapshot="教师资格证",
            level_code="SECONDARY",
            masked_no="******1234",
            issuer_name="教育行政部门",
            issue_date=date(2024, 7, 1),
            valid_from=date(2024, 7, 1),
            valid_to=None,
            status="ACTIVE",
            current_verification_status="VERIFIED",
            last_verified_at=self.updated_at,
            self_reported=False,
            updated_at=self.updated_at,
        )
        self._rows(credential_model, [credential])

        result = hr09_self_provider(self.context)

        credential_model.objects.filter.assert_called_once_with(
            tenant_id=77,
            person_id=self.context.person_id,
        )
        item = result.data["credentials"][0]
        self.assertEqual(item["maskedCertificateNo"], "******1234")
        self.assertNotIn("certificateNoHash", item)
        self.assertNotIn("certificateNoCipher", item)
        self.assertEqual(result.meta["authority"], "HR09_QUALIFICATION_AUTHORITY")

    def test_hr10_missing_legacy_mapping_is_unavailable_not_fake_empty(self):
        context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id=self.context.staff_id,
            person_id=self.context.person_id,
            legacy_employee_id=None,
        )

        result = hr10_self_provider(context)

        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.error_code, "SOURCE_IDENTITY_MAPPING_UNAVAILABLE")
        self.assertIsNone(result.data)

    @patch("hr10_development.models.development_fact.HrDevelopmentFact")
    def test_hr10_uses_resolved_legacy_mapping_with_tenant_scope(self, fact_model):
        fact = SimpleNamespace(
            id=1001,
            fact_type="TRAINING_COMPLETION",
            activity_type="TEACHING_SKILL",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 3),
            verified_hours=Decimal("18.0"),
            verified_days=3,
            verified_credits=Decimal("1.5"),
            level_or_result="PASS",
            verification_status="HR_VERIFIED",
            generated_at=self.updated_at,
            valid_from=date(2026, 7, 3),
            valid_to=None,
            supersedes_fact_id=None,
            updated_at=self.updated_at,
        )
        self._rows(fact_model, [fact])

        result = hr10_self_provider(self.context)

        fact_model.objects.filter.assert_called_once_with(
            tenant_id=77,
            staff_master_id=51,
        )
        self.assertEqual(result.data["developmentFacts"][0]["verifiedHours"], "18.0")
        self.assertEqual(result.meta["authority"], "HR10_DEVELOPMENT_AUTHORITY")

    @patch("hr_assessment.models.result.HrFinalAssessmentResult")
    @patch("hr_assessment.models.case.HrAssessmentCase")
    def test_hr12_scopes_cases_to_self_before_reading_final_results(self, case_model, result_model):
        case = SimpleNamespace(
            id="00000000-0000-0000-0000-000000001201",
            assessment_type="ANNUAL",
            cycle_id="00000000-0000-0000-0000-000000001202",
            policy_version_id="00000000-0000-0000-0000-000000001203",
            status="CLOSED",
            updated_at=self.updated_at,
        )
        final_result = SimpleNamespace(
            id="00000000-0000-0000-0000-000000001204",
            case_id=case.id,
            assessment_type="ANNUAL",
            cycle_id=case.cycle_id,
            grade_code="A",
            calculated_score=Decimal("92.50"),
            status="FINALIZED",
            result_version_no=1,
            finalized_at=self.updated_at,
            created_at=self.updated_at,
            updated_at=self.updated_at,
        )
        self._rows(case_model, [case])
        self._rows(result_model, [final_result])

        result = hr12_self_provider(self.context)

        case_model.objects.filter.assert_called_once_with(
            tenant_id=77,
            staff_id=self.context.staff_id,
        )
        result_model.objects.filter.assert_called_once_with(
            tenant_id=77,
            case_id__in=[case.id],
        )
        self.assertEqual(result.data["finalResults"][0]["calculatedScore"], "92.50")
        self.assertEqual(result.meta["authority"], "HR12_ASSESSMENT_AUTHORITY")

    @patch("hr_title.models.ProfessionalTitleResult")
    @patch("hr_title.models.TitleApplicationCase")
    def test_hr13_scopes_application_and_result_to_person(self, application_model, result_model):
        application = SimpleNamespace(
            id="00000000-0000-0000-0000-000000001301",
            case_no="TITLE-2026-001",
            batch_no="TITLE-2026",
            requested_title_code="LECTURER",
            requested_title_name="讲师",
            status="PUBLICITY",
            submitted_at=self.updated_at,
            updated_at=self.updated_at,
        )
        title_result = SimpleNamespace(
            id="00000000-0000-0000-0000-000000001302",
            result_no="TITLE-R-2026-001",
            application_case_id=application.id,
            title_code="LECTURER",
            title_name="讲师",
            title_series_code="TEACHING",
            title_level_code="INTERMEDIATE",
            effective_from=date(2026, 9, 1),
            effective_to=None,
            status="EFFECTIVE",
            supersedes_result_id=None,
            created_at=self.updated_at,
            updated_at=self.updated_at,
        )
        self._rows(application_model, [application])
        self._rows(result_model, [title_result])

        result = hr13_self_provider(self.context)

        application_model.objects.filter.assert_called_once_with(
            tenant_id=77,
            person_id=self.context.person_id,
        )
        result_model.objects.filter.assert_called_once_with(
            tenant_id=77,
            person_id=self.context.person_id,
        )
        self.assertEqual(result.data["professionalTitleResults"][0]["titleName"], "讲师")
        self.assertEqual(result.meta["authority"], "HR13_TITLE_AUTHORITY")

    @patch("hr_payroll.models.PayrollPeriod")
    @patch("hr_payroll.models.PayrollResultFact")
    @patch("hr_payroll.models.PayrollProfile")
    def test_hr15_projects_self_payroll_facts_without_payment_credentials(
        self,
        profile_model,
        result_model,
        period_model,
    ):
        profile = SimpleNamespace(
            id="00000000-0000-0000-0000-000000001501",
            pay_group_code="TEACHER",
            currency_code="CNY",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            status="ACTIVE",
            payment_account_ref="secret-account-ref",
            payroll_identity_no="secret-payroll-id",
            created_at=self.updated_at,
            updated_at=self.updated_at,
        )
        payroll_result = SimpleNamespace(
            id="00000000-0000-0000-0000-000000001502",
            result_no="PAY-2026-08-001",
            payroll_period_id="00000000-0000-0000-0000-000000001503",
            currency_code="CNY",
            gross_amount=Decimal("10000.00"),
            deduction_amount=Decimal("1200.00"),
            net_amount=Decimal("8800.00"),
            status="FINALIZED",
            supersedes_result_id=None,
            created_at=self.updated_at,
            updated_at=self.updated_at,
        )
        period = SimpleNamespace(
            id=payroll_result.payroll_period_id,
            period_code="2026-08",
            end_date=date(2026, 8, 31),
            created_at=self.updated_at,
            updated_at=self.updated_at,
        )
        self._rows(profile_model, [profile])
        self._rows(result_model, [payroll_result])
        period_model.objects.filter.return_value.order_by.return_value = [period]

        result = hr15_self_provider(self.context)

        profile_model.objects.filter.assert_called_once_with(
            tenant_id=77,
            staff_id=self.context.staff_id,
        )
        result_model.objects.filter.assert_called_once_with(
            tenant_id=77,
            staff_id=self.context.staff_id,
        )
        item = result.data["payrollProfiles"][0]
        self.assertNotIn("paymentAccountRef", item)
        self.assertNotIn("payrollIdentityNo", item)
        self.assertEqual(result.data["payrollResults"][0]["netAmount"], "8800.00")
        self.assertEqual(result.meta["authority"], "HR15_PAYROLL_AUTHORITY")

    def test_default_registry_contains_the_eight_strong_business_domains(self):
        registered = set(default_self_provider_registry().registered_domains())
        self.assertTrue(
            {"HR07", "HR09", "HR10", "HR12", "HR13", "HR14", "HR15", "HR16"}.issubset(registered)
        )

    @override_settings(HR17_SELF_PROVIDER_PATHS={"HR15": "missing.module.legacy_provider"})
    @patch("hr_self.services.authority_providers.hr15_self_provider")
    def test_runtime_configuration_cannot_shadow_canonical_hr15(self, canonical_provider):
        canonical_provider.return_value = SelfProviderResult.ok(
            {"source": "canonical-HR15"},
            provider_version="canonical-test",
        )

        result = default_self_provider_registry().call("HR15", self.context)

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data["source"], "canonical-HR15")
