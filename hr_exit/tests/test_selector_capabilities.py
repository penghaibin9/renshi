import uuid

from django.test import TestCase

from hr_exit.models import ExitCase
from hr_exit.selectors import dashboard_snapshot


class Hr16SelectorCapabilityTests(TestCase):
    def test_dashboard_reports_real_approval_workflow(self):
        ExitCase.objects.create(
            tenant_id=77,
            case_no="EXIT-2026-001",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            exit_type=ExitCase.ExitType.RESIGNATION,
            status=ExitCase.Status.SUBMITTED,
        )
        ExitCase.objects.create(
            tenant_id=77,
            case_no="EXIT-2026-002",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            exit_type=ExitCase.ExitType.TRANSFER_OUT,
            status=ExitCase.Status.APPROVED,
        )

        payload = dashboard_snapshot(77)

        self.assertTrue(payload["capabilities"]["approvalWorkflow"])
        self.assertEqual(payload["summary"]["awaitingApproval"], 1)
        self.assertEqual(payload["summary"]["approved"], 1)
        self.assertEqual(len(payload["recentCases"]), 2)

    def test_dashboard_case_counts_are_tenant_scoped(self):
        common = {
            "person_id": uuid.uuid4(),
            "employment_relationship_id": uuid.uuid4(),
            "exit_type": ExitCase.ExitType.RETIREMENT,
            "status": ExitCase.Status.SUBMITTED,
        }
        ExitCase.objects.create(tenant_id=77, case_no="EXIT-77", **common)
        ExitCase.objects.create(tenant_id=88, case_no="EXIT-88", **common)

        payload = dashboard_snapshot(77)

        self.assertEqual(payload["summary"]["cases"], 1)
        self.assertEqual(payload["summary"]["awaitingApproval"], 1)
        self.assertEqual([row["case_no"] for row in payload["recentCases"]], ["EXIT-77"])
