from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from hr_onboarding.constants import MaterialBlockingPhase, RiskCode
from hr_onboarding.jobs.reminders import report_risk
from hr_onboarding.models import (
    HrOnboardingCase,
    HrOnboardingMaterialRequirement,
    HrOnboardingTemplate,
    HrOnboardingTemplateVersion,
    HrReportDelay,
)
from hr_structure.models import HrPositionReservation


class OnboardingRiskReminderTests(TestCase):
    tenant_id = 5501

    def setUp(self):
        template = HrOnboardingTemplate.objects.create(
            tenant_id=self.tenant_id,
            code="STANDARD",
            name="标准入职",
        )
        version = HrOnboardingTemplateVersion.objects.create(
            tenant_id=self.tenant_id,
            template=template,
            version_no=1,
        )
        HrOnboardingMaterialRequirement.objects.create(
            tenant_id=self.tenant_id,
            template_version=version,
            material_type="ID_CARD",
            label="身份证明",
            required=True,
            blocking_phase=MaterialBlockingPhase.PRE_REPORT,
        )
        reservation = HrPositionReservation.objects.create(
            tenant_id=self.tenant_id,
            reservation_no="RES-RISK-1",
            source_domain="HR04",
            source_business_type="PROPOSED_HIRE",
            source_business_id="hire-risk-1",
            expires_at=timezone.now() + timedelta(days=2),
            idempotency_key="risk-reservation-1",
        )
        self.case = HrOnboardingCase.objects.create(
            tenant_id=self.tenant_id,
            case_no="ONB-RISK-1",
            source_type="HR04_HIRE",
            source_id="hire-risk-1",
            expected_report_date=timezone.localdate() + timedelta(days=3),
            template_version=version,
            position_reservation_id=reservation,
        )
        for index in range(2):
            HrReportDelay.objects.create(
                tenant_id=self.tenant_id,
                case=self.case,
                old_date=timezone.localdate() + timedelta(days=index),
                new_date=timezone.localdate() + timedelta(days=index + 1),
            )

    def test_all_case_owned_risks_are_derived_from_authoritative_facts(self):
        risks = report_risk(tenant_id=self.tenant_id)
        codes = {row["risk"] for row in risks if row["case_id"] == str(self.case.id)}

        self.assertEqual(
            codes,
            {
                RiskCode.REPORT_DATE_NEAR_NO_CONFIRM,
                RiskCode.POSITION_RESERVATION_EXPIRING,
                RiskCode.MISSING_BLOCKING_DOCUMENT,
                RiskCode.PORTAL_NOT_ACTIVATED,
                RiskCode.DELAYED_MULTIPLE_TIMES,
            },
        )

    def test_other_tenant_never_leaks_into_risk_output(self):
        self.assertEqual(report_risk(tenant_id=self.tenant_id + 1), [])
