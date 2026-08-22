from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_recruitment.integrations.hr05 import (
    Hr05OnboardingConsumer,
    Hr05OnboardingConsumerError,
)


class Hr05OnboardingConsumerTests(SimpleTestCase):
    @patch("hr_onboarding.services.case_service.CaseService")
    @patch("hr_recruitment.models.HrRecruitmentOffer")
    @patch("hr_recruitment.models.HrProposedHire")
    def test_maps_authoritative_hr04_facts_into_hr05_case(
        self,
        proposed_model,
        offer_model,
        case_service_cls,
    ):
        candidate = SimpleNamespace(legal_name="张老师")
        application = SimpleNamespace(id="app-1", candidate_id=candidate)
        position = SimpleNamespace(
            organization_id=101,
            post_catalog_id=202,
            position_id=303,
        )
        proposed = SimpleNamespace(
            id="hire-1",
            application_id=application,
            recruitment_position_id=position,
            reservation_id="404",
        )
        offer = SimpleNamespace(
            employment_type="FULL_TIME",
            expected_report_date=date(2026, 9, 1),
        )

        proposed_model.objects.select_related.return_value.filter.return_value.first.return_value = proposed
        offer_model.objects.filter.return_value.order_by.return_value.first.return_value = offer
        case_service = case_service_cls.return_value
        case_service.create_case_from_handoff.return_value = {"case_id": "case-123"}

        result = Hr05OnboardingConsumer(actor_user_id=88).handle(
            tenant_id=77,
            proposed_hire_id="hire-1",
            idempotency_key="handoff-1",
        )

        self.assertEqual(result, "case-123")
        case_service_cls.assert_called_once_with(tenant_id=77, actor_user_id=88)
        case_service.create_case_from_handoff.assert_called_once()
        request, idem = case_service.create_case_from_handoff.call_args.args
        self.assertEqual(idem, "handoff-1")
        self.assertEqual(
            request,
            {
                "tenant_id": 77,
                "source_type": "HR04_HIRE",
                "source_id": "hire-1",
                "hr04_proposed_hire_id": "hire-1",
                "hr04_application_id": "app-1",
                "position_reservation_id": 404,
                "planned_organization_id": 101,
                "planned_post_catalog_id": 202,
                "planned_position_id": 303,
                "employment_type": "FULL_TIME",
                "staff_category": "TEACHER",
                "expected_report_date": date(2026, 9, 1),
                "legal_name": "张老师",
                "preferred_name": "",
            },
        )

    def test_requires_concrete_tenant(self):
        with self.assertRaises(Hr05OnboardingConsumerError):
            Hr05OnboardingConsumer().handle(
                tenant_id=0,
                proposed_hire_id="hire-1",
                idempotency_key="handoff-1",
            )

    @patch("hr_recruitment.models.HrRecruitmentOffer")
    @patch("hr_recruitment.models.HrProposedHire")
    def test_rejects_non_numeric_hr02_reservation_id(
        self,
        proposed_model,
        offer_model,
    ):
        proposed = SimpleNamespace(
            id="hire-1",
            application_id=SimpleNamespace(
                id="app-1",
                candidate_id=SimpleNamespace(legal_name="张老师"),
            ),
            recruitment_position_id=SimpleNamespace(
                organization_id=101,
                post_catalog_id=202,
                position_id=303,
            ),
            reservation_id="not-an-int",
        )
        offer = SimpleNamespace(
            employment_type="FULL_TIME",
            expected_report_date=date(2026, 9, 1),
        )
        proposed_model.objects.select_related.return_value.filter.return_value.first.return_value = proposed
        offer_model.objects.filter.return_value.order_by.return_value.first.return_value = offer

        with self.assertRaises(Hr05OnboardingConsumerError):
            Hr05OnboardingConsumer().handle(
                tenant_id=77,
                proposed_hire_id="hire-1",
                idempotency_key="handoff-1",
            )
