import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_exit.models import ExitCase
from hr_exit.services.case_service import (
    ExitCaseError,
    ExitCaseInput,
    ExitCaseService,
)


class ExitCaseServiceTests(TestCase):
    def _case(self, status):
        case = MagicMock()
        case.id = "case-1"
        case.status = status
        case.requested_date = date(2026, 8, 1)
        case.last_working_date = date(2026, 8, 31)
        case.planned_employment_end_date = date(2026, 9, 1)
        return case

    def test_create_draft_is_tenant_scoped_and_blocks_second_open_case(self):
        service = ExitCaseService(77, actor_user_id=9)
        service._lock_relationship = MagicMock(return_value=SimpleNamespace(id=uuid.uuid4()))
        person_id = uuid.uuid4()
        relationship_id = uuid.uuid4()
        payload = ExitCaseInput(
            case_no=" EXIT-2026-001 ",
            person_id=person_id,
            employment_relationship_id=relationship_id,
            exit_type="resignation",
            requested_date=date(2026, 8, 1),
            last_working_date=date(2026, 8, 31),
            planned_employment_end_date=date(2026, 9, 1),
        )

        case = service.create_draft(payload)

        self.assertEqual(case.tenant_id, 77)
        self.assertEqual(case.case_no, "EXIT-2026-001")
        self.assertEqual(case.person_id, person_id)
        self.assertEqual(case.employment_relationship_id, relationship_id)
        self.assertEqual(case.exit_type, ExitCase.ExitType.RESIGNATION)
        self.assertEqual(case.status, ExitCase.Status.DRAFT)
        service._lock_relationship.assert_called_once_with(relationship_id, person_id)

        with self.assertRaises(ExitCaseError) as ctx:
            service.create_draft(
                ExitCaseInput(
                    case_no="EXIT-2026-002",
                    person_id=person_id,
                    employment_relationship_id=relationship_id,
                    exit_type=ExitCase.ExitType.RESIGNATION,
                )
            )
        self.assertEqual(ctx.exception.code, "EXIT_CASE_ALREADY_OPEN")
        self.assertEqual(
            ExitCase.objects.filter(
                tenant_id=77,
                employment_relationship_id=relationship_id,
            ).count(),
            1,
        )

    @patch("hr_staff.models.HrEmploymentRelationship.objects")
    def test_create_relationship_must_be_active_and_owned_by_person(self, relationship_objects):
        service = ExitCaseService(77)
        relationship = SimpleNamespace(
            id=uuid.uuid4(),
            status="ACTIVE",
            staff_id=SimpleNamespace(person_id_id=uuid.uuid4()),
        )
        relationship_objects.select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = relationship

        with self.assertRaises(ExitCaseError) as ctx:
            service._lock_relationship(relationship.id, uuid.uuid4())
        self.assertEqual(ctx.exception.code, "EXIT_RELATIONSHIP_PERSON_MISMATCH")

        person_id = relationship.staff_id.person_id_id
        relationship.status = "ENDED"
        with self.assertRaises(ExitCaseError) as ctx:
            service._lock_relationship(relationship.id, person_id)
        self.assertEqual(ctx.exception.code, "EXIT_RELATIONSHIP_NOT_ACTIVE")

    def test_create_draft_rejects_invalid_exit_type_and_date_order(self):
        service = ExitCaseService(77)
        service._lock_relationship = MagicMock()
        base = dict(
            case_no="EXIT-INVALID",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
        )
        with self.assertRaises(ExitCaseError) as ctx:
            service.create_draft(ExitCaseInput(**base, exit_type="OTHER"))
        self.assertEqual(ctx.exception.code, "EXIT_TYPE_INVALID")
        service._lock_relationship.assert_not_called()

        with self.assertRaises(ExitCaseError) as ctx:
            service.create_draft(
                ExitCaseInput(
                    **base,
                    exit_type=ExitCase.ExitType.RETIREMENT,
                    last_working_date=date(2026, 9, 2),
                    planned_employment_end_date=date(2026, 9, 1),
                )
            )
        self.assertEqual(ctx.exception.code, "EXIT_WORKING_DATE_AFTER_END_DATE")
        service._lock_relationship.assert_not_called()

    @patch("hr_exit.services.case_service.ExitCase.objects")
    def test_submit_is_tenant_scoped(self, case_objects):
        case = self._case(ExitCase.Status.DRAFT)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        ExitCaseService(77, actor_user_id=9).submit("case-1")

        case_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="case-1", tenant_id=77
        )
        self.assertEqual(case.status, ExitCase.Status.SUBMITTED)

    @patch("hr_exit.services.case_service.ExitCase.objects")
    def test_return_is_not_reject(self, case_objects):
        returned = self._case(ExitCase.Status.SUBMITTED)
        rejected = self._case(ExitCase.Status.SUBMITTED)
        case_objects.select_for_update.return_value.filter.return_value.first.side_effect = [
            returned,
            rejected,
        ]
        service = ExitCaseService(77)

        service.return_for_correction("return")
        service.reject("reject")

        self.assertEqual(returned.status, ExitCase.Status.RETURNED)
        self.assertEqual(rejected.status, ExitCase.Status.REJECTED)

    @patch("hr_exit.services.case_service.ExitCase.objects")
    def test_approval_requires_employment_end_date(self, case_objects):
        case = self._case(ExitCase.Status.SUBMITTED)
        case.planned_employment_end_date = None
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaisesRegex(ExitCaseError, "required before approval"):
            ExitCaseService(77).approve("case-1")

        case.save.assert_not_called()

    @patch("hr_exit.services.case_service.ExitCase.objects")
    def test_last_working_date_cannot_follow_employment_end(self, case_objects):
        case = self._case(ExitCase.Status.SUBMITTED)
        case.last_working_date = date(2026, 9, 2)
        case.planned_employment_end_date = date(2026, 9, 1)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaisesRegex(ExitCaseError, "cannot be later"):
            ExitCaseService(77).approve("case-1")

        case.save.assert_not_called()

    @patch("hr_exit.services.case_service.ExitCase.objects")
    def test_settlement_requires_handover(self, case_objects):
        case = self._case(ExitCase.Status.APPROVED)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaisesRegex(ExitCaseError, "cannot transition"):
            ExitCaseService(77).begin_settlement("case-1")

        case.save.assert_not_called()

    @patch("hr_exit.services.case_service.ExitCase.objects")
    def test_approved_case_cannot_use_preapproval_cancel(self, case_objects):
        case = self._case(ExitCase.Status.APPROVED)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaisesRegex(ExitCaseError, "cannot transition"):
            ExitCaseService(77).cancel_before_approval("case-1")

        case.save.assert_not_called()
