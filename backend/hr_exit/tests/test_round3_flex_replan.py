"""Round 3 MySQL integration coverage for controlled flexible-retirement replanning."""

from datetime import date, timedelta
from unittest.mock import patch

from hr_staff.tests.round2_support import MySQLRound2Case
from hr_exit.flex_models import RetirementFlexEvent
from hr_exit.models import ExitCase
from hr_exit.services.case_service import ExitCaseError, ExitCaseService
from hr_exit.services.flex_service import (
    FlexRetirementService,
    approved_plan_for_case,
)
from hr_exit.services.handover_service import ExitHandoverService
from hr_exit.services.retirement_policy_service import (
    RetirementPolicyService,
    RetirementPrecheckService,
)


class FlexibleRetirementReplanMySQLTests(MySQLRound2Case):
    def setUp(self):
        super().setUp()
        clock = patch("django.utils.timezone.localdate", return_value=date(2026, 2, 1))
        clock.start()
        self.addCleanup(clock.stop)

        policy_service = RetirementPolicyService(self.tenant, self.reviewer.pk)
        policy = policy_service.create_draft(
            policy_code="R3-ORDINARY-M",
            retirement_type="STATUTORY",
            retirement_age_months=720,
            effective_from=date(2025, 1, 1),
            gender_code="M",
            staff_category_code="TEACHER",
            relationship_type="REGULAR_EMPLOYMENT",
            transition_birth_start=date(1965, 1, 1),
            delay_step_birth_months=4,
            max_retirement_age_months=756,
            rationale="Round3 controlled replan fixture",
        )
        policy_service.activate(policy.id)
        self.precheck = RetirementPrecheckService(self.tenant, self.user.pk).evaluate(
            person_id=self.person.id,
            employment_relationship_id=self.relationship.id,
            as_of=date(2026, 2, 1),
            idempotency_key="r3-precheck-001",
        ).precheck
        self.notice = self.evidence("round3 retirement notice", "RETIREMENT_NOTICE")
        self.approval = self.evidence("round3 retirement approval", "RETIREMENT_APPROVAL")
        self.contribution = self.evidence("round3 retirement contribution", "RETIREMENT_CONTRIBUTION")
        self.agreement = self.evidence("round3 retirement agreement", "RETIREMENT_AGREEMENT")
        self.self_service = FlexRetirementService(self.tenant, self.user.pk)
        self.manager = FlexRetirementService(self.tenant, self.reviewer.pk)

    def _review(self, app, *, agreement_date):
        return self.manager.review(
            app.id,
            expected_version=app.version,
            action="APPROVE",
            reason="Independent Round3 personnel review",
            review={
                "capacity": "PUBLIC_TECHNICAL",
                "contributionMonths": 360,
                "agreementDate": agreement_date.isoformat(),
                "approvalMaterialVersionId": str(self.approval.id),
                "contributionMaterialVersionId": str(self.contribution.id),
                "agreementMaterialVersionId": str(self.agreement.id),
            },
        )

    def _approved_delay_with_approved_exit(self):
        app, _ = self.self_service.create(
            staff_id=self.staff.id,
            precheck_id=self.precheck.id,
            mode="DELAY",
            requested_date="2027-05-01",
            reason="Original voluntary delayed retirement",
            idempotency_key="r3-delay-parent",
        )
        app = self.self_service.submit(
            app.id,
            staff_id=self.staff.id,
            expected_version=app.version,
            notice_version_id=self.notice.id,
        )
        app = self._review(app, agreement_date=date(2026, 2, 1))
        app = self.manager.open_exit_case(app.id, expected_version=app.version)
        case_service = ExitCaseService(self.tenant, self.reviewer.pk)
        case_service.submit(app.exit_case_id)
        case_service.approve(app.exit_case_id)
        return app

    def _approved_end_delay(self, parent):
        active_day = self.precheck.statutory_date
        requested = parent.requested_date - timedelta(days=1)
        self.assertGreaterEqual(requested, active_day)
        with patch("django.utils.timezone.localdate", return_value=active_day):
            app, _ = self.self_service.create(
                staff_id=self.staff.id,
                precheck_id=self.precheck.id,
                mode="END_DELAY",
                requested_date=requested.isoformat(),
                reason="Both parties agreed to end the delay earlier",
                idempotency_key="r3-end-delay",
                parent_id=parent.id,
            )
            app = self.self_service.submit(
                app.id,
                staff_id=self.staff.id,
                expected_version=app.version,
                notice_version_id=self.notice.id,
            )
            app = self._review(app, agreement_date=active_day)
        return app

    def test_approved_exit_is_reopened_and_old_plan_is_audited(self):
        parent = self._approved_delay_with_approved_exit()
        case_id = parent.exit_case_id
        successor = self._approved_end_delay(parent)

        successor = self.manager.open_exit_case(
            successor.id, expected_version=successor.version
        )
        case = ExitCase.objects.get(tenant_id=self.tenant, id=case_id)
        self.assertEqual(successor.exit_case_id, case_id)
        self.assertEqual(case.status, ExitCase.Status.RETURNED)
        self.assertEqual(case.requested_date, successor.requested_date)
        self.assertEqual(case.last_working_date, successor.requested_date)
        self.assertEqual(case.planned_employment_end_date, successor.requested_date)
        self.assertIsNone(case.planned_access_end_at)

        event = RetirementFlexEvent.objects.get(
            tenant_id=self.tenant,
            application_id=successor.id,
            action="EXIT_CASE_REPLANNED",
        )
        self.assertEqual(event.payload["detail"]["previousPlan"]["status"], "APPROVED")
        self.assertEqual(event.payload["detail"]["caseId"], str(case_id))
        self.assertEqual(approved_plan_for_case(self.tenant, case_id).id, successor.id)

    def test_handover_items_block_automatic_replan(self):
        parent = self._approved_delay_with_approved_exit()
        case_service = ExitCaseService(self.tenant, self.reviewer.pk)
        case_service.begin_handover(parent.exit_case_id)
        ExitHandoverService(self.tenant, self.reviewer.pk).add_item(
            case_id=parent.exit_case_id,
            item_no="R3-HANDOVER-001",
            category_code="ASSET",
            title="Return assigned equipment",
        )
        successor = self._approved_end_delay(parent)

        with self.assertRaises(ExitCaseError) as ctx:
            self.manager.open_exit_case(successor.id, expected_version=successor.version)
        self.assertEqual(ctx.exception.code, "EXIT_RETIREMENT_HANDOVER_REVISION_REQUIRED")

        case = ExitCase.objects.get(tenant_id=self.tenant, id=parent.exit_case_id)
        self.assertEqual(case.status, ExitCase.Status.HANDOVER)
        self.assertEqual(case.planned_employment_end_date, parent.requested_date)
        successor.refresh_from_db()
        self.assertIsNone(successor.exit_case_id)


