import uuid
from unittest.mock import patch

from django.db import DatabaseError
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

    def test_pending_cohort_migration_keeps_core_dashboard_readable(self):
        class LegacyPolicyQuerySet:
            def filter(self, **_kwargs):
                return self

            def count(self):
                return 1

            def order_by(self, *_fields):
                return self

            def __getitem__(self, _key):
                return self

            def values(self, *fields):
                if "transition_birth_start" in fields:
                    raise DatabaseError("cohort columns are not ready")
                return [{"id": uuid.uuid4(), "policy_code": "RETIRE-LEGACY"}]

        with patch(
            "hr_exit.selectors.RetirementPolicy.objects.filter",
            return_value=LegacyPolicyQuerySet(),
        ):
            payload = dashboard_snapshot(77)

        self.assertEqual(payload["summary"]["activeRetirementPolicies"], 1)
        self.assertIsNone(
            payload["recentRetirementPolicies"][0]["transition_birth_start"]
        )
        self.assertFalse(payload["capabilities"]["retirementPolicy"])
        self.assertFalse(payload["capabilities"]["retirementPrecheck"])
        self.assertIn(
            "暂停预审",
            payload["capabilityReasons"]["retirementPrecheck"],
        )
