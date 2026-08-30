import json
import uuid
from types import SimpleNamespace
from unittest import mock

from django.test import RequestFactory, SimpleTestCase, TestCase

from hr_changes.api.base import make_hr_change_context
from hr_changes.api import correction as correction_api
from hr_changes.constants import CaseStatus
from hr_changes.context import HrChangeContextError
from hr_changes.models import HrChangeCorrection, HrChangeOutboxEvent
from hr_changes.services.correction_service import CorrectionService, CorrectionServiceError
from hr_changes.tests.factories import make_case
from hr_staff.models import HrCorrectionCase, HrOutboxEvent


TENANT = 61


class TenantMembershipFailClosedTests(SimpleTestCase):
    def test_empty_allowed_tenant_set_denies_instead_of_granting_global_access(self):
        request = RequestFactory().get("/api/hr/v1/changes", {"tenant_id": TENANT})
        request.user = mock.Mock(is_superuser=False, id=7)
        with mock.patch(
            "hr_changes.api.base.resolve_tenant_from_request", return_value=TENANT
        ), mock.patch("base.auth_backends.get_allowed_company_ids", return_value=set()):
            with self.assertRaises(HrChangeContextError) as caught:
                make_hr_change_context(request)
        self.assertEqual(caught.exception.code, "TENANT_CONTEXT_REQUIRED")

    def test_explicit_membership_allows_requested_tenant(self):
        request = RequestFactory().get("/api/hr/v1/changes", {"tenant_id": TENANT})
        request.user = mock.Mock(is_superuser=False, id=7)
        with mock.patch(
            "hr_changes.api.base.resolve_tenant_from_request", return_value=TENANT
        ), mock.patch("base.auth_backends.get_allowed_company_ids", return_value={TENANT}):
            context = make_hr_change_context(request)
        self.assertEqual(context.tenant_id, TENANT)


class CorrectionApiContractTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = mock.Mock(is_authenticated=True, is_superuser=True, id=9001)
        self.context = SimpleNamespace(tenant_id=TENANT)

    @staticmethod
    def _correction():
        return SimpleNamespace(
            id=uuid.uuid4(),
            change_case_id_id=uuid.uuid4(),
            correction_type="TARGET_VALUE",
            requested_values_json={"items": []},
            reason="test",
            status="APPROVED",
            previous_snapshot_hash="before",
            new_snapshot_hash="",
            authority_version=3,
            provider_code="HR03_FORMAL_CORRECTION",
            provider_case_id=None,
            provider_case_version=None,
            applied_fields_json=[],
            apply_error="",
            version=4,
        )

    def test_apply_forwards_if_match_and_idempotency_key_to_service(self):
        request = self.factory.post(
            "/api/hr/v1/corrections/x/apply",
            data=json.dumps({}),
            content_type="application/json",
            HTTP_IF_MATCH='"4"',
            HTTP_IDEMPOTENCY_KEY="api-apply-1",
        )
        request.user = self.user
        service = mock.Mock()
        service.apply.return_value = self._correction()
        correction_id = uuid.uuid4()
        with mock.patch.object(
            correction_api, "_context", return_value=(self.context, None)
        ), mock.patch.object(correction_api, "_svc", return_value=service):
            response = correction_api.correction_action(request, correction_id, "apply")
        self.assertEqual(response.status_code, 200)
        service.apply.assert_called_once_with(
            correction_id,
            expected_version=4,
            idempotency_key="api-apply-1",
        )

    def test_create_forwards_case_and_authority_versions_and_idempotency(self):
        body = {
            "version": 8,
            "authorityVersion": 5,
            "requestedValues": {"fields": {"person.preferred_name": "新名"}},
            "reason": "录入错误",
        }
        request = self.factory.post(
            "/api/hr/v1/changes/x/corrections",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="api-create-1",
        )
        request.user = self.user
        service = mock.Mock()
        service.create_correction.return_value = self._correction()
        case_id = uuid.uuid4()
        with mock.patch.object(
            correction_api, "_context", return_value=(self.context, None)
        ), mock.patch.object(correction_api, "_svc", return_value=service):
            response = correction_api.create_correction(request, case_id)
        self.assertEqual(response.status_code, 201)
        service.create_correction.assert_called_once_with(
            case_id=case_id,
            correction_type="TARGET_VALUE",
            requested_values=body["requestedValues"],
            reason="录入错误",
            authority_version=5,
            idempotency_key="api-create-1",
            case_version=8,
            evidence_material_id=None,
        )


class CorrectionAuthorityProviderTests(TestCase):
    def setUp(self):
        self.case = make_case(TENANT, status=CaseStatus.EFFECTIVE)
        self.service = CorrectionService(TENANT, actor_user_id=9001)

    def _create(self, *, key="create-1", fields=None):
        return self.service.create_correction(
            case_id=self.case.id,
            correction_type="TARGET_VALUE",
            requested_values={
                "fields": fields or {"person.preferred_name": "正式更正名"}
            },
            reason="录入错误",
            authority_version=self.case.staff_master_id.version,
            idempotency_key=key,
            case_version=self.case.version,
        )

    def _approve(self, correction):
        correction = self.service.submit(correction.id)
        return self.service.approve(correction.id)

    def test_apply_writes_hr03_authority_and_both_outboxes_atomically(self):
        correction = self._approve(self._create())
        result = self.service.apply(
            correction.id,
            expected_version=correction.version,
            idempotency_key="apply-1",
        )

        self.case.staff_master_id.person_id.refresh_from_db()
        self.case.refresh_from_db()
        self.assertEqual(
            self.case.staff_master_id.person_id.preferred_name, "正式更正名"
        )
        self.assertEqual(self.case.status, CaseStatus.CORRECTED)
        self.assertEqual(result.status, HrChangeCorrection.Status.APPLIED)
        self.assertTrue(result.provider_case_id)
        self.assertEqual(result.applied_fields_json, ["person.preferred_name"])
        self.assertTrue(
            HrCorrectionCase.objects.filter(
                tenant_id=TENANT,
                id=result.provider_case_id,
                status="APPLIED",
            ).exists()
        )
        self.assertTrue(
            HrOutboxEvent.objects.filter(
                tenant_id=TENANT,
                event_type="hr.staff.staff.basic_info_corrected",
            ).exists()
        )
        self.assertTrue(
            HrChangeOutboxEvent.objects.filter(
                tenant_id=TENANT,
                event_type="hr.change.personnel_change.corrected",
                correlation_id="apply-1",
            ).exists()
        )
        self.assertTrue(
            self.case.transitions.filter(action="correct", request_id="apply-1").exists()
        )

    def test_apply_replay_is_idempotent_and_does_not_duplicate_provider_case(self):
        correction = self._approve(self._create())
        first = self.service.apply(
            correction.id,
            expected_version=correction.version,
            idempotency_key="apply-replay",
        )
        second = self.service.apply(
            correction.id,
            expected_version=correction.version,
            idempotency_key="apply-replay",
        )
        self.assertEqual(first.id, second.id)
        self.assertEqual(HrCorrectionCase.objects.filter(tenant_id=TENANT).count(), 1)
        self.assertEqual(
            HrChangeOutboxEvent.objects.filter(
                event_id=f"hr06-correction-{correction.id}-applied"
            ).count(),
            1,
        )

    def test_create_replay_returns_same_record_but_payload_change_conflicts(self):
        first = self._create(key="create-replay")
        second = self._create(key="create-replay")
        self.assertEqual(first.id, second.id)
        with self.assertRaises(CorrectionServiceError) as caught:
            self._create(
                key="create-replay",
                fields={"person.preferred_name": "另一个值"},
            )
        self.assertEqual(caught.exception.code, "IDEMPOTENCY_KEY_CONFLICT")

    def test_non_whitelisted_business_field_is_rejected_before_record_creation(self):
        with self.assertRaises(CorrectionServiceError) as caught:
            self._create(fields={"assignment.position": "forbidden"})
        self.assertEqual(caught.exception.code, "CHANGE_CORRECTION_FIELD_DENIED")
        self.assertFalse(HrChangeCorrection.objects.filter(tenant_id=TENANT).exists())

    def test_missing_if_match_rejects_apply_without_side_effects(self):
        correction = self._approve(self._create())
        with self.assertRaises(CorrectionServiceError) as caught:
            self.service.apply(
                correction.id,
                expected_version=None,
                idempotency_key="apply-no-version",
            )
        self.assertEqual(caught.exception.code, "VERSION_REQUIRED")
        correction.refresh_from_db()
        self.assertEqual(correction.status, HrChangeCorrection.Status.APPROVED)
        self.assertFalse(HrCorrectionCase.objects.filter(tenant_id=TENANT).exists())

    def test_authority_change_after_approval_fails_closed_without_partial_hr03_case(self):
        correction = self._approve(self._create())
        person = self.case.staff_master_id.person_id
        person.preferred_name = "并发修改"
        person.version += 1
        person.save(update_fields=["preferred_name", "version", "updated_at"])

        with self.assertRaises(CorrectionServiceError) as caught:
            self.service.apply(
                correction.id,
                expected_version=correction.version,
                idempotency_key="apply-stale-authority",
            )
        self.assertEqual(caught.exception.code, "AUTHORITY_VERSION_CONFLICT")
        correction.refresh_from_db()
        self.case.refresh_from_db()
        person.refresh_from_db()
        self.assertEqual(correction.status, HrChangeCorrection.Status.FAILED)
        self.assertEqual(self.case.status, CaseStatus.EFFECTIVE)
        self.assertEqual(person.preferred_name, "并发修改")
        self.assertFalse(HrCorrectionCase.objects.filter(tenant_id=TENANT).exists())
        self.assertTrue(
            HrChangeOutboxEvent.objects.filter(
                tenant_id=TENANT,
                event_type="hr.change.personnel_change.apply_failed",
            ).exists()
        )

    def test_second_field_failure_rolls_back_first_authority_write(self):
        original_name = self.case.staff_master_id.person_id.preferred_name
        correction = self._approve(
            self._create(
                fields={
                    "person.preferred_name": "不应残留",
                    "contact.work_email": "not-an-email",
                }
            )
        )
        hr03_outbox_before = HrOutboxEvent.objects.filter(tenant_id=TENANT).count()
        with self.assertRaises(CorrectionServiceError):
            self.service.apply(
                correction.id,
                expected_version=correction.version,
                idempotency_key="apply-rollback",
            )

        self.case.staff_master_id.person_id.refresh_from_db()
        correction.refresh_from_db()
        self.assertEqual(
            self.case.staff_master_id.person_id.preferred_name, original_name
        )
        self.assertEqual(correction.status, HrChangeCorrection.Status.FAILED)
        self.assertFalse(HrCorrectionCase.objects.filter(tenant_id=TENANT).exists())
        self.assertEqual(
            HrOutboxEvent.objects.filter(tenant_id=TENANT).count(),
            hr03_outbox_before,
        )
