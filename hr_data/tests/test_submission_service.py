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
        snapshot.definition_code = "EDU-HR-01"
        snapshot.definition_version = 1
        snapshot.as_of_date = date(2026, 8, 1)
        snapshot.scope_json = {"asOfEvidenceId": "evidence-1"}
        snapshot.receipt_ref = ""
        return snapshot

    def _evidence(self, status=AsOfEvidenceSnapshot.Status.COMPLETE):
        evidence = MagicMock()
        evidence.id = "evidence-1"
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
    def test_draft_cannot_skip_approval_and_submit(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.DRAFT)
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot
        with self.assertRaisesRegex(SubmissionLifecycleError, "cannot transition to SUBMITTED"):
            SubmissionLifecycleService(77).submit("submission-1")
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_submit_records_submission_time_without_mutating_payload_identity(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.APPROVED)
        payload_hash = snapshot.payload_hash
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot
        SubmissionLifecycleService(77).submit("submission-1")
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.SUBMITTED)
        self.assertEqual(snapshot.payload_hash, payload_hash)
        self.assertIsNotNone(snapshot.submitted_at)
        snapshot.save.assert_called_once_with(
            update_fields=["status", "submitted_at", "updated_by", "updated_at"]
        )

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_receipt_requires_submitted_state_and_reference(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.SUBMITTED)
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot
        with self.assertRaisesRegex(SubmissionLifecycleError, "receipt_ref is required"):
            SubmissionLifecycleService(77).record_receipt(
                "submission-1", accepted=False, receipt_ref=""
            )
        snapshot.save.assert_not_called()

    @patch("hr_data.services.submission_service.SubmissionSnapshot.objects")
    def test_rejected_receipt_does_not_rewrite_payload(self, objects):
        snapshot = self._snapshot(SubmissionSnapshot.Status.SUBMITTED)
        payload_hash = snapshot.payload_hash
        objects.select_for_update.return_value.filter.return_value.first.return_value = snapshot
        SubmissionLifecycleService(77).record_receipt(
            "submission-1", accepted=False, receipt_ref="receipt-9"
        )
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.REJECTED)
        self.assertEqual(snapshot.receipt_ref, "receipt-9")
        self.assertEqual(snapshot.payload_hash, payload_hash)
