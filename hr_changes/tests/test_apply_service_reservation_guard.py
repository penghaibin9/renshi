from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_changes.constants import ChangeActionCode
from hr_changes.integrations.hr02 import Hr02GateError
from hr_changes.services.apply_service import ApplyService, ApplyServiceError


class ApplyServiceReservationGuardTests(SimpleTestCase):
    @patch("hr_changes.services.apply_service._resolve_staff", return_value=None)
    @patch("hr_changes.services.apply_service._resolve_catalog", return_value=None)
    @patch("hr_changes.services.apply_service._resolve_position")
    @patch("hr_changes.services.apply_service._resolve_org", return_value=None)
    @patch("hr_staff.services.assignment_service.AssignmentService")
    def test_position_transfer_requires_reservation_commit_after_switch_primary(
        self,
        assignment_service_cls,
        resolve_org,
        resolve_position,
        resolve_catalog,
        resolve_staff,
    ):
        resolve_position.return_value = SimpleNamespace(id=5)
        assignment_service_cls.return_value.switch_primary.return_value = SimpleNamespace(id=100)

        service = object.__new__(ApplyService)
        service.tenant_id = 77
        service.actor_user_id = 1
        service.position_gate = MagicMock()
        service.position_gate.needs_position.return_value = True
        service.position_gate.require_commit_for_case.side_effect = Hr02GateError(
            "CHANGE_POSITION_RESERVATION_MISSING",
            "目标岗位预占缺失，禁止生效",
        )

        case = SimpleNamespace(
            id=9,
            case_no="CHG-9",
            action_id=SimpleNamespace(code=ChangeActionCode.POSITION_TRANSFER),
            proposals=MagicMock(),
            target_org_id_id=None,
            target_position_id_id=5,
            employment_relationship_id="rel-1",
        )
        case.proposals.all.return_value = []

        with self.assertRaisesRegex(ApplyServiceError, "目标岗位预占缺失") as ctx:
            service._apply_domain(case, date(2026, 8, 10))

        self.assertEqual(ctx.exception.code, "CHANGE_POSITION_RESERVATION_MISSING")
        service.position_gate.require_commit_for_case.assert_called_once_with(case)

    @patch("hr_changes.services.apply_service._resolve_staff", return_value=None)
    @patch("hr_changes.services.apply_service._resolve_catalog", return_value=None)
    @patch("hr_changes.services.apply_service._resolve_position", return_value=None)
    @patch("hr_changes.services.apply_service._resolve_org", return_value=None)
    @patch("hr_staff.services.assignment_service.AssignmentService")
    def test_org_only_transfer_does_not_require_position_reservation(
        self,
        assignment_service_cls,
        resolve_org,
        resolve_position,
        resolve_catalog,
        resolve_staff,
    ):
        assignment_service_cls.return_value.switch_primary.return_value = SimpleNamespace(id=100)

        service = object.__new__(ApplyService)
        service.tenant_id = 77
        service.actor_user_id = 1
        service.position_gate = MagicMock()
        service.position_gate.needs_position.return_value = False

        case = SimpleNamespace(
            id=9,
            case_no="CHG-9",
            action_id=SimpleNamespace(code=ChangeActionCode.ORG_TRANSFER),
            proposals=MagicMock(),
            target_org_id_id=3,
            target_position_id_id=None,
            employment_relationship_id="rel-1",
        )
        case.proposals.all.return_value = []

        result = service._apply_domain(case, date(2026, 8, 10))

        service.position_gate.require_commit_for_case.assert_not_called()
        self.assertIn("100", result["target_fact_ids"])
