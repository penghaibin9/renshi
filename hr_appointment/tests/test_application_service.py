import uuid
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentBatch,
    AppointmentPositionSupplySnapshot,
)
from hr_appointment.services.application_service import (
    AppointmentApplicationError,
    AppointmentApplicationInput,
    AppointmentApplicationService,
)


class AppointmentApplicationServiceTests(TestCase):
    def _case(self, status):
        case = MagicMock()
        case.id = "case-1"
        case.batch_no = "B-OPEN"
        case.status = status
        return case

    def _open_batch_with_supply(self, *, level="PT-7"):
        batch = AppointmentBatch.objects.create(
            tenant_id=77,
            batch_no=f"B-{uuid.uuid4().hex[:6]}",
            name="2026 专技岗位竞聘",
            policy_version_id=uuid.uuid4(),
            status=AppointmentBatch.Status.APPLICATION_OPEN,
        )
        AppointmentPositionSupplySnapshot.objects.create(
            tenant_id=77,
            batch=batch,
            position_instance_id=1001,
            organization_id=11,
            category_code="PROFESSIONAL_TECHNICAL",
            level_code=level,
            authorized_fte=1,
            occupied_fte=0,
            reserved_fte=0,
            available_fte=1,
            snapshot_at=timezone.now(),
        )
        return batch

    def test_create_draft_uses_frozen_batch_policy_position_and_level(self):
        batch = self._open_batch_with_supply(level="PT-7")
        payload = AppointmentApplicationInput(
            case_no=" CASE-001 ",
            person_id=uuid.uuid4(),
            policy_version_id=batch.policy_version_id,
            position_instance_id=1001,
            batch_no=batch.batch_no,
            requested_level_code="",
        )

        case = AppointmentApplicationService(77, actor_user_id=9).create_draft(payload)

        self.assertEqual(case.case_no, "CASE-001")
        self.assertEqual(case.policy_version_id, batch.policy_version_id)
        self.assertEqual(case.position_instance_id, 1001)
        self.assertEqual(case.batch_no, batch.batch_no)
        self.assertEqual(case.requested_level_code, "PT-7")
        self.assertEqual(case.status, AppointmentApplicationCase.Status.DRAFT)

    def test_create_draft_rejects_policy_level_and_supply_spoofing(self):
        batch = self._open_batch_with_supply(level="PT-7")
        service = AppointmentApplicationService(77)
        base = dict(
            case_no="CASE-002",
            person_id=uuid.uuid4(),
            policy_version_id=batch.policy_version_id,
            position_instance_id=1001,
            batch_no=batch.batch_no,
            requested_level_code="PT-7",
        )

        with self.assertRaises(AppointmentApplicationError) as ctx:
            service.create_draft(
                AppointmentApplicationInput(**{**base, "policy_version_id": uuid.uuid4()})
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_POLICY_VERSION_MISMATCH")

        with self.assertRaises(AppointmentApplicationError) as ctx:
            service.create_draft(
                AppointmentApplicationInput(**{**base, "requested_level_code": "PT-6"})
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_APPLICATION_LEVEL_MISMATCH")

        with self.assertRaises(AppointmentApplicationError) as ctx:
            service.create_draft(
                AppointmentApplicationInput(**{**base, "position_instance_id": 9999})
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_POSITION_NOT_IN_FROZEN_SUPPLY")
        self.assertFalse(AppointmentApplicationCase.objects.filter(tenant_id=77).exists())

    def test_closed_batch_cannot_accept_new_draft(self):
        batch = self._open_batch_with_supply()
        batch.status = AppointmentBatch.Status.APPLICATION_CLOSED
        batch.save(update_fields=["status", "updated_at"])

        with self.assertRaises(AppointmentApplicationError) as ctx:
            AppointmentApplicationService(77).create_draft(
                AppointmentApplicationInput(
                    case_no="CASE-CLOSED",
                    person_id=uuid.uuid4(),
                    policy_version_id=batch.policy_version_id,
                    position_instance_id=1001,
                    batch_no=batch.batch_no,
                    requested_level_code="PT-7",
                )
            )

        self.assertEqual(ctx.exception.code, "APPOINTMENT_BATCH_NOT_OPEN")

    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_submit_is_tenant_scoped(self, case_objects):
        case = self._case(AppointmentApplicationCase.Status.DRAFT)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case
        service = AppointmentApplicationService(77, actor_user_id=9)
        service._lock_open_batch = MagicMock(return_value=SimpleNamespace(batch_no="B-OPEN"))

        result = service.submit("case-1")

        self.assertIs(result, case)
        case_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="case-1", tenant_id=77
        )
        service._lock_open_batch.assert_called_once_with("B-OPEN")
        self.assertEqual(case.status, AppointmentApplicationCase.Status.SUBMITTED)

    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_return_is_not_reject(self, case_objects):
        returned = self._case(AppointmentApplicationCase.Status.SUBMITTED)
        rejected = self._case(AppointmentApplicationCase.Status.SUBMITTED)
        case_objects.select_for_update.return_value.filter.return_value.first.side_effect = [
            returned,
            rejected,
        ]
        service = AppointmentApplicationService(77)

        service.return_for_correction("return")
        service.reject_eligibility("reject")

        self.assertEqual(returned.status, AppointmentApplicationCase.Status.RETURNED)
        self.assertEqual(rejected.status, AppointmentApplicationCase.Status.REJECTED)

    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_rejected_case_cannot_resubmit(self, case_objects):
        case = self._case(AppointmentApplicationCase.Status.REJECTED)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case
        service = AppointmentApplicationService(77)
        service._lock_open_batch = MagicMock()

        with self.assertRaisesRegex(AppointmentApplicationError, "cannot transition"):
            service.submit("case-1")

        case.save.assert_not_called()

    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_review_requires_eligibility(self, case_objects):
        case = self._case(AppointmentApplicationCase.Status.SUBMITTED)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaisesRegex(AppointmentApplicationError, "cannot transition"):
            AppointmentApplicationService(77).start_review("case-1")

        case.save.assert_not_called()

    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_publicity_is_last_workflow_state_before_effect_service(self, case_objects):
        case = self._case(AppointmentApplicationCase.Status.PROPOSED)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        AppointmentApplicationService(77).enter_publicity("case-1")

        self.assertEqual(case.status, AppointmentApplicationCase.Status.PUBLICITY)
        self.assertNotEqual(case.status, AppointmentApplicationCase.Status.EFFECTIVE)

    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_missing_or_cross_tenant_case_fails_closed(self, case_objects):
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = None

        with self.assertRaisesRegex(AppointmentApplicationError, "not found"):
            AppointmentApplicationService(77).submit("foreign")

        case_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="foreign", tenant_id=77
        )
