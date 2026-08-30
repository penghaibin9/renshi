import importlib
import inspect
import json
import uuid
from datetime import date, datetime, timezone
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase

from hr_contracts.models import (
    HrContractAgreement,
    HrContractCase,
    HrContractExpiryPolicy,
    HrContractExpiryRiskFact,
    HrContractVersion,
)
from hr_contracts.services.agreement_service import AgreementService
from hr_contracts.services.alert_escalation import (
    CanonicalContractExpiryService,
    ContractExpiryError,
)
from hr_staff.models import HrOutboxEvent


class CanonicalContractExpiryServiceTests(TestCase):
    tenant_id = 77
    other_tenant_id = 88
    staff_id = uuid.UUID("00000000-0000-0000-0000-000000000707")
    relationship_id = uuid.UUID("00000000-0000-0000-0000-000000007007")

    def _agreement(self, *, tenant_id=77, end=date(2026, 9, 30), suffix="A"):
        agreement = HrContractAgreement.objects.create(
            tenant_id=tenant_id,
            agreement_no=f"AGR-{tenant_id}-{suffix}",
            subject_type=HrContractAgreement.SubjectType.STAFF_EMPLOYMENT,
            staff_id=self.staff_id,
            employment_relationship_id=self.relationship_id,
            agreement_title="Fixed-term employment agreement",
            agreement_type="FIXED_TERM",
            status=HrContractAgreement.Status.ACTIVE,
            current_version_no=1,
        )
        content = {"clauses": ["canonical"], "tenantId": tenant_id}
        version = HrContractVersion.objects.create(
            tenant_id=tenant_id,
            agreement=agreement,
            version_no=1,
            version_type=HrContractVersion.VersionType.INITIAL,
            effective_from=date(2025, 10, 1),
            effective_to=end,
            signed_at=datetime(2025, 9, 20, tzinfo=timezone.utc),
            signed_document_ref=f"doc://agreement/{tenant_id}/{suffix}",
            content_snapshot_json=content,
            content_hash=AgreementService._content_hash(content),
            status=HrContractVersion.Status.EFFECTIVE,
        )
        return agreement, version

    def _policy(
        self,
        *,
        tenant_id=77,
        action="CREATE_RENEWAL_CASE",
        warning_days=30,
        critical_after_days=15,
    ):
        return HrContractExpiryPolicy.objects.create(
            tenant_id=tenant_id,
            policy_version="2026-v1",
            agreement_type="FIXED_TERM",
            warning_days=warning_days,
            critical_after_days=critical_after_days,
            action_type=action,
            active=True,
        )

    def test_before_warning_window_has_no_action(self):
        self._agreement(end=date(2026, 12, 31))
        self._policy(warning_days=30)

        outcome = CanonicalContractExpiryService(self.tenant_id).scan(
            as_of=date(2026, 8, 30)
        )

        self.assertEqual(outcome["eligible"], 0)
        self.assertEqual(outcome["createdRisks"], 0)
        self.assertFalse(HrContractCase.objects.exists())

    def test_pre_expiry_creates_submitted_renewal_and_explainable_risk(self):
        agreement, version = self._agreement(end=date(2026, 9, 20))
        self._policy(action="CREATE_RENEWAL_CASE", warning_days=30)

        outcome = CanonicalContractExpiryService(
            self.tenant_id, actor_user_id=901
        ).scan(as_of=date(2026, 8, 30))

        self.assertEqual(outcome["createdCases"], 1)
        case = HrContractCase.objects.get()
        risk = HrContractExpiryRiskFact.objects.get()
        agreement.refresh_from_db()
        self.assertEqual(case.case_type, HrContractCase.CaseType.RENEW)
        self.assertEqual(case.status, HrContractCase.Status.SUBMITTED)
        self.assertEqual(case.requested_effective_from, version.effective_to)
        self.assertEqual(agreement.status, HrContractAgreement.Status.RENEWAL_IN_PROGRESS)
        self.assertEqual(risk.risk_stage, HrContractExpiryRiskFact.Stage.EXPIRING)
        self.assertEqual(risk.action_case_id, case.id)
        self.assertEqual(risk.evidence_json["decision"], "CREATE_RENEWAL_CASE")
        self.assertEqual(len(risk.evidence_hash), 64)
        self.assertEqual(
            list(HrOutboxEvent.objects.values_list("event_type", flat=True)),
            ["hr.contracts.expiry_action.created"],
        )

    def test_overdue_manual_review_never_terminates_legal_relationship(self):
        agreement, version = self._agreement(end=date(2026, 8, 1))
        self._policy(action="MANUAL_REVIEW", critical_after_days=15)

        outcome = CanonicalContractExpiryService(self.tenant_id).scan(
            as_of=date(2026, 8, 30)
        )

        self.assertEqual(outcome["createdCases"], 1)
        case = HrContractCase.objects.get()
        risk = HrContractExpiryRiskFact.objects.get()
        agreement.refresh_from_db()
        version.refresh_from_db()
        self.assertEqual(case.case_type, HrContractCase.CaseType.REVIEW)
        self.assertEqual(case.status, HrContractCase.Status.SUBMITTED)
        self.assertEqual(risk.risk_stage, HrContractExpiryRiskFact.Stage.OVERDUE)
        self.assertEqual(risk.severity, HrContractExpiryRiskFact.Severity.CRITICAL)
        self.assertEqual(agreement.status, HrContractAgreement.Status.EXPIRED)
        self.assertEqual(version.status, HrContractVersion.Status.EFFECTIVE)
        self.assertNotEqual(agreement.status, HrContractAgreement.Status.TERMINATED)

    def test_missing_policy_and_incomplete_current_fact_fail_closed(self):
        agreement, version = self._agreement(end=date(2026, 9, 1))
        service = CanonicalContractExpiryService(self.tenant_id)

        missing_policy = service.scan(as_of=date(2026, 8, 30))
        self.assertEqual(missing_policy["blocked"], 1)
        self.assertEqual(missing_policy["blockers"][0]["code"], "EXPIRY_POLICY_REQUIRED")

        self._policy()
        # Simulate storage-level tampering. The production ORM correctly blocks
        # this mutation, so the contract test bypasses the ORM intentionally.
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE hr07_contract_version SET content_hash = %s WHERE id = %s",
                ["f" * 64, version.id.hex],
            )
        incomplete = service.scan(as_of=date(2026, 8, 30))
        self.assertEqual(incomplete["blocked"], 1)
        self.assertEqual(
            incomplete["blockers"][0]["code"], "CONTRACT_VERSION_EVIDENCE_INVALID"
        )
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, HrContractAgreement.Status.ACTIVE)
        self.assertFalse(HrContractCase.objects.exists())
        self.assertFalse(HrContractExpiryRiskFact.objects.exists())

    def test_replay_and_concurrent_worker_shape_are_idempotent(self):
        self._agreement(end=date(2026, 9, 20))
        self._policy()

        first = CanonicalContractExpiryService(self.tenant_id).scan(
            as_of=date(2026, 8, 30)
        )
        second = CanonicalContractExpiryService(self.tenant_id).scan(
            as_of=date(2026, 8, 30)
        )

        self.assertEqual(first["createdRisks"], 1)
        self.assertEqual(second["createdRisks"], 0)
        self.assertEqual(second["replayed"], 1)
        self.assertEqual(HrContractCase.objects.count(), 1)
        self.assertEqual(HrContractExpiryRiskFact.objects.count(), 1)
        self.assertEqual(HrOutboxEvent.objects.count(), 1)

    def test_ambiguous_policy_fails_closed(self):
        self._agreement(end=date(2026, 9, 20))
        self._policy()
        replacement = HrContractExpiryPolicy.objects.create(
            tenant_id=self.tenant_id,
            policy_version="2026-v2",
            agreement_type="FIXED_TERM",
            warning_days=60,
            critical_after_days=7,
            action_type=HrContractExpiryPolicy.ActionType.MANUAL_REVIEW,
            active=True,
        )

        outcome = CanonicalContractExpiryService(self.tenant_id).scan(
            as_of=date(2026, 8, 30)
        )

        self.assertEqual(outcome["blocked"], 1)
        self.assertEqual(outcome["blockers"][0]["code"], "EXPIRY_POLICY_AMBIGUOUS")
        self.assertFalse(HrContractCase.objects.exists())

        replacement.active = False
        replacement.save(update_fields=["active"])
        recovered = CanonicalContractExpiryService(self.tenant_id).scan(
            as_of=date(2026, 8, 30)
        )
        self.assertEqual(recovered["createdCases"], 1)

    @patch(
        "hr_contracts.services.alert_escalation.emit_registered_event",
        side_effect=RuntimeError("outbox unavailable"),
    )
    def test_event_failure_rolls_back_case_risk_and_projection(self, _emit):
        agreement, _version = self._agreement(end=date(2026, 9, 20))
        self._policy()

        with self.assertRaisesRegex(RuntimeError, "outbox unavailable"):
            CanonicalContractExpiryService(self.tenant_id).scan(
                as_of=date(2026, 8, 30)
            )

        agreement.refresh_from_db()
        self.assertEqual(agreement.status, HrContractAgreement.Status.ACTIVE)
        self.assertFalse(HrContractCase.objects.exists())
        self.assertFalse(HrContractExpiryRiskFact.objects.exists())

    def test_tenant_scope_cannot_scan_other_school(self):
        self._agreement(tenant_id=self.tenant_id, end=date(2026, 9, 20), suffix="OWN")
        self._agreement(
            tenant_id=self.other_tenant_id,
            end=date(2026, 9, 20),
            suffix="OTHER",
        )
        self._policy(tenant_id=self.tenant_id)
        self._policy(tenant_id=self.other_tenant_id)

        CanonicalContractExpiryService(self.tenant_id).scan(as_of=date(2026, 8, 30))

        self.assertEqual(HrContractCase.objects.count(), 1)
        self.assertEqual(HrContractCase.objects.get().tenant_id, self.tenant_id)
        self.assertFalse(
            HrContractExpiryRiskFact.objects.filter(
                tenant_id=self.other_tenant_id
            ).exists()
        )

    def test_as_of_is_mandatory_and_dry_run_has_no_writes(self):
        self._agreement(end=date(2026, 9, 20))
        self._policy()
        service = CanonicalContractExpiryService(self.tenant_id)

        with self.assertRaises(ContractExpiryError) as caught:
            service.scan(as_of=None)
        self.assertEqual(caught.exception.code, "EXPIRY_AS_OF_REQUIRED")

        outcome = service.scan(as_of=date(2026, 8, 30), dry_run=True)
        self.assertEqual(outcome["eligible"], 1)
        self.assertTrue(outcome["dryRun"])
        self.assertFalse(HrContractCase.objects.exists())
        self.assertFalse(HrContractExpiryRiskFact.objects.exists())
        self.assertFalse(HrOutboxEvent.objects.exists())

    def test_management_command_is_explicit_tenant_scoped_dry_run_worker(self):
        self._agreement(end=date(2026, 9, 20))
        self._policy()
        stdout = StringIO()

        call_command(
            "hr07_scan_expiry",
            tenant_id=self.tenant_id,
            as_of="2026-08-30",
            dry_run=True,
            stdout=stdout,
        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["tenantId"], self.tenant_id)
        self.assertTrue(payload["dryRun"])
        self.assertFalse(HrContractCase.objects.exists())
        with self.assertRaises(CommandError):
            call_command("hr07_scan_expiry", as_of="2026-08-30")


class CanonicalExpiryStaticContractTests(SimpleTestCase):
    def test_old_orphan_models_and_direct_wall_clock_are_gone(self):
        module = importlib.import_module("hr_contracts.services.alert_escalation")
        source = inspect.getsource(module)

        self.assertNotIn("HrAgreement.objects", source)
        self.assertNotIn("date.today", source)
        self.assertIn("select_for_update", source)
        self.assertIn("emit_registered_event", source)
