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
    def _evidence(self, *, tenant_id=77, status=AsOfEvidenceSnapshot.Status.COMPLETE):
        return AsOfEvidenceSnapshot.objects.create(
            tenant_id=tenant_id,
            evidence_no=f"EVID-{uuid.uuid4().hex[:8]}",
            definition_code="ACTIVE_STAFF_COUNT",
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

        replay = service.create_draft(
            submission_no="SUB-2026-001",
            as_of_evidence_id=evidence.id,
            payload_hash="A" * 64,
            scope={"organizationId": 10},
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.snapshot.id, snapshot.id)

    def test_caller_cannot_override_reserved_evidence_identity(self):
        evidence = self._evidence()
        with self.assertRaises(SubmissionLifecycleError) as ctx:
            SubmissionLifecycleService(77).create_draft(
                submission_no="SUB-SPOOF",
                as_of_evidence_id=evidence.id,
                payload_hash="a" * 64,
                scope={"asOfEvidenceId": str(uuid.uuid4())},
            )
        self.assertEqual(ctx.exception.code, "SUBMISSION_SCOPE_RESERVED_KEY")
        self.assertFalse(SubmissionSnapshot.objects.filter(tenant_id=77).exists())

    def test_cross_tenant_evidence_and_non_sha256_hash_fail_closed(self):
        foreign = self._evidence(tenant_id=88)
        service = SubmissionLifecycleService(77)
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
        snapshot = SubmissionLifecycleService(77).create_draft(
            submission_no="SUB-PARTIAL",
            as_of_evidence_id=evidence.id,
            payload_hash="a" * 64,
        ).snapshot
        with self.assertRaises(SubmissionLifecycleError) as ctx:
            SubmissionLifecycleService(77).validate(snapshot.id)
        self.assertEqual(ctx.exception.code, "SUBMISSION_ASOF_INCOMPLETE")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, SubmissionSnapshot.Status.DRAFT)

    def test_same_submission_number_with_different_payload_is_conflict(self):
        evidence = self._evidence()
        service = SubmissionLifecycleService(77)
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

    def test_submission_permission_exists_after_migrate(self):
        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="hr_data",
                content_type__model="metricdefinitionversion",
                codename="hr.data.submit",
            ).exists()
        )


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
    def _snapshot(submission_id, *, status="DRAFT", receipt_ref=""):
        return SimpleNamespace(
            id=submission_id,
            submission_no="SUB-2026-001",
            definition_code="ACTIVE_STAFF_COUNT",
            definition_version=3,
            as_of_date=date(2026, 8, 1),
            scope_json={"asOfEvidenceId": "evidence"},
            payload_hash="a" * 64,
            status=status,
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
    def test_lifecycle_transitions_use_canonical_service(self, _tenant, service_cls):
        for function, method_name, status in (
            (submission_api.validate_submission, "validate", "VALIDATED"),
            (submission_api.approve_submission, "approve", "APPROVED"),
            (submission_api.submit_submission, "submit", "SUBMITTED"),
        ):
            snapshot = self._snapshot(self.submission_id, status=status)
            setattr(service_cls.return_value, method_name, SimpleNamespace())
            getattr(service_cls.return_value, method_name).return_value = snapshot
            request = self.factory.post("/transition")
            request.user = UserStub()
            response = function(request, self.submission_id)
            self.assertEqual(response.status_code, 200)
            getattr(service_cls.return_value, method_name).assert_called_once_with(
                self.submission_id
            )
            getattr(service_cls.return_value, method_name).reset_mock()

    @patch("hr_data.submission_api.SubmissionLifecycleService")
    @patch("hr_data.submission_api.resolve_request_tenant", return_value=77)
    def test_receipt_requires_real_boolean_and_preserves_external_reference(
        self, _tenant, service_cls
    ):
        request = self.factory.post(
            "/receipt",
            data=json.dumps({"accepted": "true", "receiptRef": "R-1"}),
            content_type="application/json",
        )
        request.user = UserStub()
        response = submission_api.record_receipt(request, self.submission_id)
        self.assertEqual(response.status_code, 400)
        service_cls.return_value.record_receipt.assert_not_called()

        snapshot = self._snapshot(
            self.submission_id,
            status="ACCEPTED",
            receipt_ref="UPSTREAM-RECEIPT-9",
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
        service_cls.return_value.record_receipt.assert_called_once_with(
            self.submission_id,
            accepted=True,
            receipt_ref="UPSTREAM-RECEIPT-9",
        )
        self.assertIn(b"UPSTREAM-RECEIPT-9", response.content)
