import uuid
from datetime import date

from django.test import TestCase

from hr_exit.models import ExitCase
from hr_exit.services.case_service import ExitCaseError, ExitCasePatch, ExitCaseService


class ExitCaseAmendTests(TestCase):
    def _case(self, status=ExitCase.Status.RETURNED):
        return ExitCase.objects.create(
            tenant_id=77,
            case_no=f"EXIT-{uuid.uuid4().hex[:8]}",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            exit_type=ExitCase.ExitType.RESIGNATION,
            status=status,
            requested_date=date(2026, 8, 13),
            last_working_date=date(2026, 8, 31),
            planned_employment_end_date=date(2026, 9, 1),
        )

    def test_returned_case_can_amend_plan_without_rewriting_identity(self):
        case = self._case()
        person_id = case.person_id
        relationship_id = case.employment_relationship_id

        amended = ExitCaseService(77, actor_user_id=9).update_draft(
            case.id,
            ExitCasePatch(
                last_working_date=date(2026, 9, 2),
                planned_employment_end_date=date(2026, 9, 3),
            ),
        )

        self.assertEqual(amended.last_working_date, date(2026, 9, 2))
        self.assertEqual(amended.planned_employment_end_date, date(2026, 9, 3))
        self.assertEqual(amended.person_id, person_id)
        self.assertEqual(amended.employment_relationship_id, relationship_id)
        self.assertEqual(amended.status, ExitCase.Status.RETURNED)

    def test_amend_can_explicitly_clear_nullable_plan_fields(self):
        case = self._case()

        ExitCaseService(77).update_draft(
            case.id,
            ExitCasePatch(
                last_working_date=None,
                planned_employment_end_date=None,
            ),
        )

        case.refresh_from_db()
        self.assertIsNone(case.last_working_date)
        self.assertIsNone(case.planned_employment_end_date)

    def test_submitted_or_later_case_cannot_be_amended(self):
        case = self._case(status=ExitCase.Status.SUBMITTED)

        with self.assertRaises(ExitCaseError) as ctx:
            ExitCaseService(77).update_draft(
                case.id,
                ExitCasePatch(requested_date=date(2026, 8, 14)),
            )

        self.assertEqual(ctx.exception.code, "EXIT_CASE_NOT_EDITABLE")

    def test_amend_preserves_date_order_gate(self):
        case = self._case()

        with self.assertRaises(ExitCaseError) as ctx:
            ExitCaseService(77).update_draft(
                case.id,
                ExitCasePatch(
                    last_working_date=date(2026, 9, 4),
                    planned_employment_end_date=date(2026, 9, 3),
                ),
            )

        self.assertEqual(ctx.exception.code, "EXIT_WORKING_DATE_AFTER_END_DATE")
        case.refresh_from_db()
        self.assertEqual(case.last_working_date, date(2026, 8, 31))
        self.assertEqual(case.planned_employment_end_date, date(2026, 9, 1))
