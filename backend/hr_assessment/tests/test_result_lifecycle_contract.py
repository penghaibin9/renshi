"""Non-database production contracts for the HR12 result lifecycle."""

import inspect

from django.test import SimpleTestCase
from django.urls import reverse

from horilla.hr_event_registry import global_event_registry
from hr_assessment.models.result import (
    HrAcknowledgement,
    HrAssessmentArchivePackage,
    HrResultNotice,
)
from hr_assessment.context import resolve_authenticated_staff_id
from hr_assessment.permissions import require_assessment_permission
from hr_assessment.providers.interfaces import ArchiveProvider, NotificationProvider
from hr_assessment.services.finalization_service import AssessmentFinalizationService
from hr_assessment.services.result_lifecycle_service import (
    AssessmentResultLifecycleService,
)
from hr_assessment.services.objection_service import AssessmentObjectionService


class ResultLifecycleContractTests(SimpleTestCase):
    def test_registered_result_lifecycle_events_exist(self):
        for event_name in (
            "hr.assessment.assessment_result.finalized",
            "hr.assessment.assessment_result.notified",
            "hr.assessment.assessment_result.acknowledged",
            "hr.assessment.assessment_result.archived",
        ):
            self.assertTrue(global_event_registry.contains(event_name, 1), event_name)

    def test_finalization_persists_transactional_outbox_event(self):
        source = inspect.getsource(AssessmentFinalizationService.finalize)
        self.assertIn("emit_registered_event", source)
        self.assertIn("hr.assessment.assessment_result.finalized", source)

    def test_delivery_and_archive_are_receipt_backed(self):
        delivery_source = inspect.getsource(
            AssessmentResultLifecycleService.confirm_delivery
        )
        archive_source = inspect.getsource(AssessmentResultLifecycleService.archive)
        self.assertIn("ASSESSMENT_DELIVERY_RECEIPT_REQUIRED", delivery_source)
        self.assertIn("delivery_receipt_ref", delivery_source)
        self.assertIn("ASSESSMENT_ARCHIVE_DELIVERY_ACK_REQUIRED", archive_source)
        self.assertIn("ASSESSMENT_ARCHIVE_OBJECTION_OPEN", archive_source)
        self.assertIn("sha256", archive_source)

    def test_acknowledgement_is_self_scoped(self):
        source = inspect.getsource(AssessmentResultLifecycleService.acknowledge)
        self.assertIn("ASSESSMENT_ACK_SELF_SCOPE_REQUIRED", source)
        self.assertIn("case.staff_id", source)

    def test_request_guard_revalidates_school_and_staff_mapping(self):
        guard_source = inspect.getsource(require_assessment_permission)
        mapping_source = inspect.getsource(resolve_authenticated_staff_id)
        self.assertIn("get_allowed_company_ids", guard_source)
        self.assertIn("resolve_authenticated_staff_id", guard_source)
        self.assertIn("HrAccountLink.objects.filter", mapping_source)
        self.assertIn("legacy_employee_id", mapping_source)
        self.assertIn("SELF_STAFF_MAPPING_AMBIGUOUS", mapping_source)

    def test_database_idempotency_constraints_exist(self):
        names = {
            constraint.name
            for model in (HrResultNotice, HrAcknowledgement, HrAssessmentArchivePackage)
            for constraint in model._meta.constraints
        }
        self.assertTrue(
            {
                "hr12_notice_tenant_no_uq",
                "hr12_notice_result_version_uq",
                "hr12_ack_result_version_uq",
                "hr12_archive_result_version_uq",
            }.issubset(names)
        )

    def test_lifecycle_api_routes_are_registered(self):
        result_id = "00000000-0000-0000-0000-000000000101"
        notice_id = "00000000-0000-0000-0000-000000000102"
        self.assertIn(
            result_id,
            reverse("hr_assessment_api:hr12-api-result-notice", args=[result_id]),
        )
        self.assertIn(
            notice_id,
            reverse(
                "hr_assessment_api:hr12-api-result-notice-delivery",
                args=[notice_id],
            ),
        )
        self.assertIn(
            result_id,
            reverse(
                "hr_assessment_api:hr12-api-result-acknowledgement",
                args=[result_id],
            ),
        )
        self.assertIn(
            result_id,
            reverse("hr_assessment_api:hr12-api-result-archive", args=[result_id]),
        )
        self.assertEqual(
            reverse("hr_assessment_api:hr12-api-result-lifecycle-list"),
            "/api/v1/hr/assessments/results/lifecycle",
        )
        self.assertIn(
            result_id,
            reverse(
                "hr_assessment_api:hr12-api-result-objection-submit",
                args=[result_id],
            ),
        )

    def test_archive_and_notification_providers_require_persisted_facts(self):
        archive_source = inspect.getsource(ArchiveProvider._do_fetch)
        notice_source = inspect.getsource(NotificationProvider._do_fetch)
        self.assertIn('archive_status="ARCHIVED"', archive_source)
        self.assertIn("contentHash", archive_source)
        self.assertIn('delivery_status="DELIVERED"', notice_source)
        self.assertIn('delivery_receipt_ref__gt=""', notice_source)

    def test_chinese_acknowledgement_dictionary_is_consistent(self):
        source = inspect.getsource(AssessmentResultLifecycleService.acknowledge)
        self.assertIn("RECEIVED_RESERVATION", source)
        self.assertIn("RECEIVED_DISAGREE", source)
        self.assertNotIn("RECEIVED_WITH_OPINION", source)

    def test_upheld_objection_cannot_close_without_formal_revision(self):
        source = inspect.getsource(AssessmentObjectionService.decide)
        self.assertIn("AssessmentResultCorrectionService", source)
        self.assertIn("resolution_revision_id = revision.id", source)
        self.assertIn("assessment_objection.decided", source)

    def test_closed_objection_requires_exact_idempotent_replay(self):
        source = inspect.getsource(AssessmentObjectionService.decide)
        self.assertIn("ASSESSMENT_OBJECTION_IDEMPOTENCY_CONFLICT", source)
        self.assertIn("replay_revision", source)
