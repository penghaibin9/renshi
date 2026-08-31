from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_data.models import AsOfEvidenceSnapshot, SubmissionSnapshot
from hr_data.services.submission_service import (
    SubmissionLifecycleError,
    SubmissionLifecycleService,
)


class SubmissionLifecycleServiceTests(TestCase):
    def _snapshot(self, status):
        snapshot = MagicMock()
        snapshot.id = "submission-1"
        snapshot.status = status
        snapshot.payload_hash = "a" * 64
        snapshot.definition_kind = AsOfEvidenceSnapshot.DefinitionKind.METRIC
        snapshot.definition_code = "EDU-HR-01"
        snapshot.definition_version = 1
        snapshot.as_of_date = date(2026, 8, 1)
        snapshot.scope_json = {"asOfEvidenceId": "evidence-1"}
        snapshot.dispatch_ref = ""
        snapshot.dispatch_error = ""
        snapshot.receipt_ref = ""
        snapshot.created_by = 3
        return snapshot

    def _evidence(self, status=AsOfEvidenceSnapshot.Status.COMPLETE):
        evidence = MagicMock()
        evidence.id = "evidence-1"
        evidence.definition_kind = AsOfEvidenceSnapshot.DefinitionKind.METRIC
        evidence.definition_code = "EDU-HR-01"
        evidence.definition_version = 1
        evidence.as_of_date = date(2026, 8, 1)
        evidence.status = status
        evidence.evidence_hash = "b" * 64
        return evidence

    @patch("hr_data.services.submission_service.AsOfEvidenceSnapshot.objects")
    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_validate_is_tenant_scoped_and_requires_matching_complete_evidence(
        self, objects, evidence_objects
    ):
        snapshot = self._snapshot(SubmissionSnapshot.Status.DRAFT)
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot
        evidence = self._evidence()
        evidence_objects.select_for_update.return_value.filter.return_value.first.return_value = evidence

        SubmissionLifecycleService(77, actor_user_id=9).validate("submission-1")

        objects.select_for_update.return_value.filter.assert_called_once_with(
            id="submission-1", tenant_id=77
        )
        evidence_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="evidence-1", tenant_id=77
        )
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.VALIDATED)

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_missing_asof_evidence_reference_cannot_validate(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.DRAFT)
        snapshot.scope_json = {}
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot
        with self.assertRaisesRegex(SubmissionLifecycleError, "asOfEvidenceId"):
            SubmissionLifecycleService(77).validate("submission-1")
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.AsOfEvidenceSnapshot.objects")
    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_partial_asof_evidence_cannot_validate(self, objects, evidence_objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.DRAFT)
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot
        evidence_objects.select_for_update.return_value.filter.return_value.first.return_value = self._evidence(
            AsOfEvidenceSnapshot.Status.PARTIAL
        )
        with self.assertRaisesRegex(SubmissionLifecycleError, "PARTIAL"):
            SubmissionLifecycleService(77).validate("submission-1")
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.AsOfEvidenceSnapshot.objects")
    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_definition_or_asof_mismatch_cannot_validate(self, objects, evidence_objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.DRAFT)
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot
        evidence = self._evidence()
        evidence.definition_version = 2
        evidence_objects.select_for_update.return_value.filter.return_value.first.return_value = evidence
        with self.assertRaisesRegex(SubmissionLifecycleError, "does not match"):
            SubmissionLifecycleService(77).validate("submission-1")
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_invalid_payload_hash_cannot_be_validated(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.DRAFT)
        snapshot.payload_hash = "short"
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot
        with self.assertRaisesRegex(SubmissionLifecycleError, "64-character"):
            SubmissionLifecycleService(77).validate("submission-1")
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_creator_cannot_self_approve(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.VALIDATED)
        snapshot.created_by = 9
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot

        with self.assertRaises(SubmissionLifecycleError) as ctx:
            SubmissionLifecycleService(77, actor_user_id=9).approve("submission-1")

        self.assertEqual(ctx.exception.code, "SUBMISSION_SELF_APPROVAL_DENIED")
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_distinct_identified_approver_can_approve(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.VALIDATED)
        snapshot.created_by = 3
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot

        result = SubmissionLifecycleService(77, actor_user_id=9).approve("submission-1")

        self.assertIs(result, snapshot)
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.APPROVED)
        self.assertEqual(snapshot.updated_by, 9)

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_unknown_creator_cannot_be_approved(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.VALIDATED)
        snapshot.created_by = None
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot

        with self.assertRaises(SubmissionLifecycleError) as ctx:
            SubmissionLifecycleService(77, actor_user_id=9).approve("submission-1")

        self.assertEqual(ctx.exception.code, "SUBMISSION_CREATOR_UNKNOWN")
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_direct_submit_is_disabled_even_after_approval(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.APPROVED)
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot
        with self.assertRaises(SubmissionLifecycleError) as ctx:
            SubmissionLifecycleService(77).submit("submission-1")
        self.assertEqual(ctx.exception.code, "SUBMISSION_ASYNC_DISPATCH_REQUIRED")
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_direct_dispatch_confirmation_is_disabled(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.DISPATCH_QUEUED)
        snapshot.dispatch_ref = "dispatch-001"
        payload_hash = snapshot.payload_hash
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot

        with self.assertRaises(SubmissionLifecycleError) as caught:
            SubmissionLifecycleService(77, actor_user_id=9).confirm_dispatched(
                "submission-1", dispatch_ref="dispatch-001"
            )
        self.assertEqual(caught.exception.code, "SUBMISSION_TRUSTED_DISPATCH_REQUIRED")
        self.assertEqual(snapshot.payload_hash, payload_hash)
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_dispatch_confirmation_requires_exact_persisted_ref(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.DISPATCH_QUEUED)
        snapshot.dispatch_ref = "dispatch-001"
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot

        with self.assertRaises(SubmissionLifecycleError) as ctx:
            SubmissionLifecycleService(77).confirm_dispatched(
                "submission-1",
                dispatch_ref="dispatch-other",
            )
        self.assertEqual(ctx.exception.code, "SUBMISSION_TRUSTED_DISPATCH_REQUIRED")
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_direct_worker_dispatch_failure_is_disabled(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.DISPATCH_QUEUED)
        snapshot.dispatch_ref = "dispatch-001"
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot

        with self.assertRaises(SubmissionLifecycleError) as caught:
            SubmissionLifecycleService(77).record_dispatch_failure(
                "submission-1",
                dispatch_ref="dispatch-001",
                error="https://secret.internal/?token=top-secret network timeout",
            )
        self.assertEqual(caught.exception.code, "SUBMISSION_TRUSTED_DISPATCH_REQUIRED")
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_direct_receipt_api_is_disabled(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.SUBMITTED)
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot
        with self.assertRaises(SubmissionLifecycleError) as caught:
            SubmissionLifecycleService(77, actor_user_id=12).record_receipt(
                "submission-1", accepted=False, receipt_ref=""
            )
        self.assertEqual(caught.exception.code, "SUBMISSION_TRUSTED_RECEIPT_REQUIRED")
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_receipt_requires_identified_actor(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.SUBMITTED)
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot
        with self.assertRaises(SubmissionLifecycleError) as ctx:
            SubmissionLifecycleService(77).record_receipt(
                "submission-1", accepted=True, receipt_ref="receipt-9"
            )
        self.assertEqual(ctx.exception.code, "SUBMISSION_TRUSTED_RECEIPT_REQUIRED")
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_direct_rejected_receipt_cannot_rewrite_payload(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.SUBMITTED)
        payload_hash = snapshot.payload_hash
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot
        with self.assertRaises(SubmissionLifecycleError):
            SubmissionLifecycleService(77, actor_user_id=12).record_receipt(
                "submission-1", accepted=False, receipt_ref="receipt-9"
            )
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.SUBMITTED)
        self.assertEqual(snapshot.payload_hash, payload_hash)
