import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import RequestFactory, SimpleTestCase, TestCase

from hr_data import submission_api
from hr_data.models import AsOfEvidenceSnapshot, SubmissionSnapshot
from hr_data.services.submission_service import (
    SubmissionLifecycleError,
    SubmissionLifecycleService,
)


class SubmissionAuthorityServiceTests(TestCase):
    def _evidence(
        self,
        *,
        tenant_id=77,
        status=AsOfEvidenceSnapshot.Status.COMPLETE,
        definition_code="ACTIVE_STAFF_COUNT",
    ):
        return AsOfEvidenceSnapshot.objects.create(
            tenant_id=tenant_id,
            evidence_no=f"EVID-{uuid.uuid4().hex[:8]}",
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
            definition_code=definition_code,
            definition_version=3,
            as_of_date=date(2026, 8, 1),
            status=status,
            source_statuses_json={"HR03": "OK"},
            blocked_domains_json=[],
            provider_versions_json={"HR03": "1.0"},
            evidence_hash="b" * 64,
        )

    def test_draft_identity_is_derived_from_tenant_owned_evidence(self):
        evidence = self._evidence()
        service = SubmissionLifecycleService(77, actor_user_id=9)

        outcome = service.create_draft(
            submission_no="SUB-2026-001",
            as_of_evidence_id=evidence.id,
            payload_hash="a" * 64,
            scope={"organizationId": 10},
        )

        self.assertTrue(outcome.created)
        snapshot = outcome.snapshot
        self.assertEqual(snapshot.definition_code, evidence.definition_code)
        self.assertEqual(snapshot.definition_version, evidence.definition_version)
        self.assertEqual(snapshot.as_of_date, evidence.as_of_date)
        self.assertEqual(snapshot.scope_json["asOfEvidenceId"], str(evidence.id))
        self.assertEqual(snapshot.scope_json["organizationId"], 10)
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.DRAFT)
        self.assertEqual(snapshot.created_by, 9)

        replay = service.create_draft(
            submission_no="SUB-2026-001",
            as_of_evidence_id=evidence.id,
            payload_hash="A" * 64,
            scope={"organizationId": 10},
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.snapshot.id, snapshot.id)

    def test_formal_draft_requires_identifiable_actor(self):
        evidence = self._evidence()
        with self.assertRaises(SubmissionLifecycleError) as ctx:
            SubmissionLifecycleService(77).create_draft(
                submission_no="SUB-NO-ACTOR",
                as_of_evidence_id=evidence.id,
                payload_hash="a" * 64,
            )
        self.assertEqual(ctx.exception.code, "SUBMISSION_ACTOR_REQUIRED")

    def test_caller_cannot_override_reserved_evidence_identity(self):
        evidence = self._evidence()
        with self.assertRaises(SubmissionLifecycleError) as ctx:
            SubmissionLifecycleService(77, actor_user_id=9).create_draft(
                submission_no="SUB-SPOOF",
                as_of_evidence_id=evidence.id,
                payload_hash="a" * 64,
                scope={"asOfEvidenceId": str(uuid.uuid4())},
            )
        self.assertEqual(ctx.exception.code, "SUBMISSION_SCOPE_RESERVED_KEY")
        self.assertFalse(SubmissionSnapshot.objects.filter(tenant_id=77).exists())

    def test_cross_tenant_evidence_and_non_sha256_hash_fail_closed(self):
        foreign = self._evidence(tenant_id=88)
        service = SubmissionLifecycleService(77, actor_user_id=9)
        with self.assertRaises(SubmissionLifecycleError) as ctx:
            service.create_draft(
                submission_no="SUB-XTENANT",
                as_of_evidence_id=foreign.id,
                payload_hash="a" * 64,
            )
        self.assertEqual(ctx.exception.code, "SUBMISSION_ASOF_EVIDENCE_NOT_FOUND")

        local = self._evidence()
        for bad_hash in ("a" * 63, "g" * 64, "not-a-hash"):
            with self.assertRaises(SubmissionLifecycleError) as ctx:
                service.create_draft(
                    submission_no=f"SUB-BAD-{len(bad_hash)}",
                    as_of_evidence_id=local.id,
                    payload_hash=bad_hash,
                )
            self.assertEqual(ctx.exception.code, "SUBMISSION_PAYLOAD_HASH_INVALID")

    def test_partial_evidence_can_be_staged_but_cannot_validate(self):
        evidence = self._evidence(status=AsOfEvidenceSnapshot.Status.PARTIAL)
        snapshot = SubmissionLifecycleService(77, actor_user_id=9).create_draft(
            submission_no="SUB-PARTIAL",
            as_of_evidence_id=evidence.id,
            payload_hash="a" * 64,
        ).snapshot
        with self.assertRaises(SubmissionLifecycleError) as ctx:
            SubmissionLifecycleService(77, actor_user_id=9).validate(snapshot.id)
        self.assertEqual(ctx.exception.code, "SUBMISSION_ASOF_INCOMPLETE")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.DRAFT)

    def test_accepted_correction_preserves_chain_and_supersedes_parent(self):
        original_evidence = self._evidence()
        service = SubmissionLifecycleService(77, actor_user_id=9)
        original = service.create_draft(
            submission_no="SUB-ORIGINAL",
            as_of_evidence_id=original_evidence.id,
            payload_hash="a" * 64,
        ).snapshot
        original.status = SubmissionSnapshot.Status.REJECTED
        original.receipt_ref = "receipt-original-rejected"
        original.save(update_fields=["status", "receipt_ref", "updated_at"])

        correction_evidence = self._evidence()
        correction = service.create_correction(
            original.id,
            submission_no="SUB-CORRECTION-1",
            as_of_evidence_id=correction_evidence.id,
            payload_hash="c" * 64,
            scope={"correctionReasonCode": "SOURCE_FIXED"},
        ).snapshot

        self.assertEqual(correction.parent_submission_id, original.id)
        self.assertEqual(correction.status, SubmissionSnapshot.Status.DRAFT)
        self.assertEqual(original.payload_hash, "a" * 64)

        correction.status = SubmissionSnapshot.Status.SUBMITTED
        correction.save(update_fields=["status", "updated_at"])
        service.record_receipt(
            correction.id,
            accepted=True,
            receipt_ref="receipt-correction-accepted",
        )

        original.refresh_from_db()
        correction.refresh_from_db()
        self.assertEqual(original.status, SubmissionSnapshot.Status.CORRECTED)
        self.assertEqual(original.receipt_ref, "receipt-original-rejected")
        self.assertEqual(correction.status, SubmissionSnapshot.Status.ACCEPTED)
        self.assertEqual(correction.receipt_ref, "receipt-correction-accepted")

    def test_correction_rejects_non_terminal_parent_and_definition_spoof(self):
        evidence = self._evidence()
        service = SubmissionLifecycleService(77, actor_user_id=9)
        draft = service.create_draft(
            submission_no="SUB-NOT-TERMINAL",
            as_of_evidence_id=evidence.id,
            payload_hash="a" * 64,
        ).snapshot
        with self.assertRaises(SubmissionLifecycleError) as ctx:
            service.create_correction(
                draft.id,
                submission_no="SUB-INVALID-CORRECTION",
                as_of_evidence_id=evidence.id,
                payload_hash="b" * 64,
            )
        self.assertEqual(ctx.exception.code, "SUBMISSION_CORRECTION_INVALID_STATE")

        draft.status = SubmissionSnapshot.Status.REJECTED
        draft.save(update_fields=["status", "updated_at"])
        foreign_definition = self._evidence(
            definition_code="OTHER-FORMAL-DEFINITION"
        )
        with self.assertRaises(SubmissionLifecycleError) as ctx:
            service.create_correction(
                draft.id,
                submission_no="SUB-SPOOF-CORRECTION",
                as_of_evidence_id=foreign_definition.id,
                payload_hash="b" * 64,
            )
        self.assertEqual(
            ctx.exception.code,
            "SUBMISSION_CORRECTION_DEFINITION_MISMATCH",
        )

    def test_same_submission_number_with_different_payload_is_conflict(self):
        evidence = self._evidence()
        service = SubmissionLifecycleService(77, actor_user_id=9)
        service.create_draft(
            submission_no="SUB-IDEM",
            as_of_evidence_id=evidence.id,
            payload_hash="a" * 64,
        )
        with self.assertRaises(SubmissionLifecycleError) as ctx:
            service.create_draft(
                submission_no="SUB-IDEM",
                as_of_evidence_id=evidence.id,
                payload_hash="c" * 64,
            )
        self.assertEqual(ctx.exception.code, "SUBMISSION_IDEMPOTENCY_CONFLICT")

    def test_submission_permissions_exist_after_migrate(self):
        codenames = set(
            Permission.objects.filter(
                content_type__app_label="hr_data",
                content_type__model="metricdefinitionversion",
                codename__in={
                    "hr.data.submit",
                    "hr.data.approve",
                    "hr.data.receipt",
                },
            ).values_list("codename", flat=True)
        )
        self.assertEqual(
            codenames,
            {"hr.data.submit", "hr.data.approve", "hr.data.receipt"},
        )

    def test_creator_and_approver_must_be_distinct(self):
        evidence = self._evidence()
        creator = SubmissionLifecycleService(77, actor_user_id=9)
        snapshot = creator.create_draft(
            submission_no="SUB-FOUR-EYES",
            as_of_evidence_id=evidence.id,
            payload_hash="a" * 64,
        ).snapshot
        creator.validate(snapshot.id)

        with self.assertRaises(SubmissionLifecycleError) as ctx:
            creator.approve(snapshot.id)
        self.assertEqual(ctx.exception.code, "SUBMISSION_SELF_APPROVAL_DENIED")

        approved = SubmissionLifecycleService(77, actor_user_id=10).approve(snapshot.id)
        self.assertEqual(approved.status, SubmissionSnapshot.Status.APPROVED)
        self.assertEqual(approved.updated_by, 10)


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88


class SubmissionAuthorityApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.submission_id = uuid.uuid4()
        self.evidence_id = uuid.uuid4()

    @staticmethod
    def _snapshot(submission_id, *, status="DRAFT", receipt_ref="", dispatch_ref=""):
        return SimpleNamespace(
            id=submission_id,
            submission_no="SUB-2026-001",
            definition_kind="METRIC",
            definition_code="ACTIVE_STAFF_COUNT",
            definition_version=3,
            as_of_date=date(2026, 8, 1),
            scope_json={"asOfEvidenceId": "evidence"},
            payload_hash="a" * 64,
            status=status,
            dispatch_ref=dispatch_ref,
            dispatch_requested_at=None,
            dispatch_error="",
            submitted_at=None,
            receipt_ref=receipt_ref,
            parent_submission_id=None,
        )

    @patch("hr_data.submission_api.SubmissionLifecycleService")
    @patch("hr_data.submission_api.resolve_request_tenant", return_value=77)
    def test_create_uses_submit_permission_and_only_evidence_identity(
        self, tenant_resolver, service_cls
    ):
        snapshot = self._snapshot(self.submission_id)
        service_cls.return_value.create_draft.return_value = SimpleNamespace(
            snapshot=snapshot, created=True
        )
        request = self.factory.post(
            "/api/v1/hr/data/submissions/",
            data=json.dumps(
                {
                    "submissionNo": "SUB-2026-001",
                    "asOfEvidenceId": str(self.evidence_id),
                    "payloadHash": "a" * 64,
                    "scope": {"organizationId": 10},
                    "definitionCode": "SPOOFED",
                    "definitionVersion": 999,
                    "asOfDate": "2030-01-01",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = submission_api.create_submission(request)

        self.assertEqual(response.status_code, 201)
        tenant_resolver.assert_called_once_with(
            request, required_permission=submission_api.SUBMIT_PERMISSION
        )
        kwargs = service_cls.return_value.create_draft.call_args.kwargs
        self.assertEqual(kwargs["as_of_evidence_id"], self.evidence_id)
        self.assertNotIn("definition_code", kwargs)
        self.assertNotIn("definition_version", kwargs)
        self.assertNotIn("as_of_date", kwargs)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_data.submission_api.SubmissionLifecycleService")
    @patch("hr_data.submission_api.resolve_request_tenant", return_value=77)
    def test_correction_endpoint_preserves_parent_and_uses_submit_permission(
        self, tenant_resolver, service_cls
    ):
        correction_id = uuid.uuid4()
        snapshot = self._snapshot(correction_id, status="DRAFT")
        snapshot.parent_submission_id = self.submission_id
        service_cls.return_value.create_correction.return_value = SimpleNamespace(
            snapshot=snapshot,
            created=True,
        )
        request = self.factory.post(
            "/corrections/",
            data=json.dumps(
                {
                    "submissionNo": "SUB-2026-001-C1",
                    "asOfEvidenceId": str(self.evidence_id),
                    "payloadHash": "c" * 64,
                    "scope": {"correctionReasonCode": "SOURCE_FIXED"},
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = submission_api.create_correction(request, self.submission_id)

        self.assertEqual(response.status_code, 201)
        tenant_resolver.assert_called_once_with(
            request,
            required_permission=submission_api.SUBMIT_PERMISSION,
        )
        service_cls.return_value.create_correction.assert_called_once_with(
            self.submission_id,
            submission_no="SUB-2026-001-C1",
            as_of_evidence_id=self.evidence_id,
            payload_hash="c" * 64,
            scope={"correctionReasonCode": "SOURCE_FIXED"},
        )
        self.assertIn(str(self.submission_id).encode(), response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_data.submission_api.SubmissionLifecycleService")
    @patch("hr_data.submission_api.resolve_request_tenant", return_value=77)
    def test_validate_keeps_submit_permission(self, tenant_resolver, service_cls):
        service_cls.return_value.validate.return_value = self._snapshot(
            self.submission_id, status="VALIDATED"
        )
        request = self.factory.post("/validate")
        request.user = UserStub()

        response = submission_api.validate_submission(request, self.submission_id)

        self.assertEqual(response.status_code, 200)
        tenant_resolver.assert_called_once_with(
            request, required_permission=submission_api.SUBMIT_PERMISSION
        )
        service_cls.return_value.validate.assert_called_once_with(self.submission_id)

    @patch("hr_data.submission_api.SubmissionLifecycleService")
    @patch("hr_data.submission_api.resolve_request_tenant", return_value=77)
    def test_approve_requires_distinct_approval_permission(
        self, tenant_resolver, service_cls
    ):
        service_cls.return_value.approve.return_value = self._snapshot(
            self.submission_id, status="APPROVED"
        )
        request = self.factory.post("/approve")
        request.user = UserStub()

        response = submission_api.approve_submission(request, self.submission_id)

        self.assertEqual(response.status_code, 200)
        tenant_resolver.assert_called_once_with(
            request, required_permission=submission_api.APPROVE_PERMISSION
        )
        service_cls.return_value.approve.assert_called_once_with(self.submission_id)

    @patch("hr_data.submission_api.SubmissionDispatchService")
    @patch("hr_data.submission_api.resolve_request_tenant", return_value=77)
    def test_submit_endpoint_only_queues_async_dispatch(
        self, tenant_resolver, dispatch_cls
    ):
        snapshot = self._snapshot(
            self.submission_id,
            status="DISPATCH_QUEUED",
            dispatch_ref="dispatch-1",
        )
        dispatch_cls.return_value.queue.return_value = SimpleNamespace(
            snapshot=snapshot,
            queued=True,
            dispatch_ref="dispatch-1",
        )
        request = self.factory.post("/submit")
        request.user = UserStub()

        response = submission_api.submit_submission(request, self.submission_id)

        self.assertEqual(response.status_code, 202)
        tenant_resolver.assert_called_once_with(
            request, required_permission=submission_api.SUBMIT_PERMISSION
        )
        dispatch_cls.assert_called_once_with(77, actor_user_id=88)
        dispatch_cls.return_value.queue.assert_called_once_with(self.submission_id)
        self.assertIn(b"DISPATCH_QUEUED", response.content)
        self.assertIn(b"dispatch-1", response.content)

    @patch("hr_data.submission_api.SubmissionLifecycleService")
    @patch("hr_data.submission_api.resolve_request_tenant", return_value=77)
    def test_receipt_requires_separate_permission_and_real_boolean(
        self, tenant_resolver, service_cls
    ):
        request = self.factory.post(
            "/receipt",
            data=json.dumps({"accepted": "true", "receiptRef": "R-1"}),
            content_type="application/json",
        )
        request.user = UserStub()
        response = submission_api.record_receipt(request, self.submission_id)
        self.assertEqual(response.status_code, 400)
        tenant_resolver.assert_called_once_with(
            request, required_permission=submission_api.RECEIPT_PERMISSION
        )
        service_cls.return_value.record_receipt.assert_not_called()

        tenant_resolver.reset_mock()
        snapshot = self._snapshot(
            self.submission_id,
            status="ACCEPTED",
            receipt_ref="UPSTREAM-RECEIPT-9",
            dispatch_ref="dispatch-1",
        )
        service_cls.return_value.record_receipt.return_value = snapshot
        request = self.factory.post(
            "/receipt",
            data=json.dumps(
                {"accepted": True, "receiptRef": "UPSTREAM-RECEIPT-9"}
            ),
            content_type="application/json",
        )
        request.user = UserStub()
        response = submission_api.record_receipt(request, self.submission_id)
        self.assertEqual(response.status_code, 200)
        tenant_resolver.assert_called_once_with(
            request, required_permission=submission_api.RECEIPT_PERMISSION
        )
        service_cls.return_value.record_receipt.assert_called_once_with(
            self.submission_id,
            accepted=True,
            receipt_ref="UPSTREAM-RECEIPT-9",
        )
        self.assertIn(b"UPSTREAM-RECEIPT-9", response.content)
