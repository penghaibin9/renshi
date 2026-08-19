"""HR09 application lifecycle with non-bypassable precheck/submission gates."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from hr_qualification.constants import (
    ApplicationStatus,
    BatchStatus,
    PrecheckResultType,
    RulePackVersionStatus,
)
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherEvidencePackage,
)
from hr_qualification.providers.base import ProviderEvidenceResult
from hr_qualification.services.evidence_service import (
    EvidenceAggregationError,
    EvidenceAggregationService,
)
from hr_qualification.services.precheck_service import PrecheckResult, PrecheckService


class ApplicationError(Exception):
    def __init__(self, code: str, message: str | None = None):
        if message is None:
            message = code
            code = "APPLICATION_ERROR"
        self.code = code
        super().__init__(message)


_TRANSITIONS: dict[str, set[str]] = {
    ApplicationStatus.DRAFT: {
        ApplicationStatus.PRECHECKING,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.CANCELLED,
    },
    ApplicationStatus.PRECHECKING: {
        ApplicationStatus.READY,
        ApplicationStatus.DRAFT,
    },
    ApplicationStatus.READY: {
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.DRAFT,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.SUBMITTED: {
        ApplicationStatus.FORMAL_REVIEW,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.RETURNED: {
        ApplicationStatus.RESUBMITTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.RESUBMITTED: {
        ApplicationStatus.FORMAL_REVIEW,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.FORMAL_REVIEW: {
        ApplicationStatus.RETURNED,
        ApplicationStatus.ELIGIBLE,
        ApplicationStatus.PANEL_REVIEW,
    },
    ApplicationStatus.ELIGIBLE: {
        ApplicationStatus.PANEL_REVIEW,
    },
    ApplicationStatus.PANEL_REVIEW: {
        ApplicationStatus.RESULT_PENDING,
    },
    ApplicationStatus.RESULT_PENDING: {
        ApplicationStatus.RECOGNIZED,
        ApplicationStatus.NOT_RECOGNIZED,
        ApplicationStatus.OBJECTION,
    },
    ApplicationStatus.OBJECTION: {
        ApplicationStatus.RESULT_PENDING,
        ApplicationStatus.WITHDRAWN,
    },
}
_GUARDED_TARGETS = {ApplicationStatus.READY, ApplicationStatus.SUBMITTED}
_PRECHECK_LEASE = timedelta(minutes=15)


class ApplicationService:
    """申报状态机服务。READY/SUBMITTED only come from dedicated gates."""

    @staticmethod
    def _lock(application: HrDoubleTeacherApplication) -> HrDoubleTeacherApplication:
        locked = (
            HrDoubleTeacherApplication.objects.select_for_update()
            .select_related("batch_id__rule_pack_version_id")
            .filter(id=application.id, tenant_id=application.tenant_id)
            .first()
        )
        if locked is None:
            raise ApplicationError(
                "APPLICATION_NOT_FOUND",
                "application not found inside tenant",
            )
        return locked

    @staticmethod
    def _assert_batch_accepts_application(application: HrDoubleTeacherApplication) -> None:
        """Enforce the batch/rule/date gate inside the service boundary.

        API callers, background workers and management commands must observe the
        same eligibility contract. A READY application cannot be submitted after
        its batch closes or its frozen rule version stops being ACTIVE.
        """
        batch = application.batch_id
        rule_version = batch.rule_pack_version_id
        today = timezone.localdate()
        if batch.status != BatchStatus.APPLICATION_OPEN:
            raise ApplicationError(
                "BATCH_NOT_OPEN",
                "recognition batch is not open for applications",
            )
        if rule_version.status != RulePackVersionStatus.ACTIVE:
            raise ApplicationError(
                "RULE_VERSION_NOT_ACTIVE",
                "recognition batch rule version is not ACTIVE",
            )
        if batch.application_start and today < batch.application_start:
            raise ApplicationError(
                "APPLICATION_NOT_STARTED",
                "recognition batch application window has not started",
            )
        if batch.application_end and today > batch.application_end:
            raise ApplicationError(
                "APPLICATION_CLOSED",
                "recognition batch application window is closed",
            )
        if batch.target_levels and application.target_level not in set(batch.target_levels):
            raise ApplicationError(
                "TARGET_LEVEL_NOT_ALLOWED",
                "application target level is not enabled by this batch",
            )

    @staticmethod
    def _set_status(application, target_status):
        application.status = target_status
        application.version += 1
        update_fields = ["status", "version", "updated_at"]
        if target_status == ApplicationStatus.SUBMITTED:
            application.submitted_at = timezone.now()
            update_fields.append("submitted_at")
        application.save(update_fields=update_fields)
        return application

    @staticmethod
    @transaction.atomic
    def transition(
        application: HrDoubleTeacherApplication,
        target_status: str,
    ) -> HrDoubleTeacherApplication:
        """Non-gated transitions only; READY/SUBMITTED use dedicated methods."""
        if target_status in _GUARDED_TARGETS:
            raise ApplicationError(
                "APPLICATION_GUARDED_TRANSITION",
                f"{target_status} requires the dedicated precheck/submission gate",
            )
        application = ApplicationService._lock(application)
        allowed = _TRANSITIONS.get(application.status, set())
        if target_status not in allowed:
            raise ApplicationError(
                "APPLICATION_INVALID_TRANSITION",
                f"Cannot transition from {application.status} to {target_status}. Allowed: {allowed}",
            )
        return ApplicationService._set_status(application, target_status)

    @staticmethod
    @transaction.atomic
    def start_precheck(application: HrDoubleTeacherApplication) -> HrDoubleTeacherApplication:
        application = ApplicationService._lock(application)
        ApplicationService._assert_batch_accepts_application(application)
        if application.status == ApplicationStatus.PRECHECKING:
            if application.updated_at > timezone.now() - _PRECHECK_LEASE:
                raise ApplicationError(
                    "APPLICATION_PRECHECK_ALREADY_RUNNING",
                    "application already has an active precheck lease",
                )
            application.version += 1
            application.save(update_fields=["version", "updated_at"])
            return application
        if application.status != ApplicationStatus.DRAFT:
            raise ApplicationError(
                "APPLICATION_PRECHECK_INVALID_STATE",
                f"precheck requires DRAFT, got {application.status}",
            )
        return ApplicationService._set_status(application, ApplicationStatus.PRECHECKING)

    @staticmethod
    @transaction.atomic
    def complete_precheck(
        application: HrDoubleTeacherApplication,
        result: PrecheckResult,
    ) -> HrDoubleTeacherApplication:
        application = ApplicationService._lock(application)
        if application.status != ApplicationStatus.PRECHECKING:
            raise ApplicationError(
                "APPLICATION_PRECHECK_INVALID_STATE",
                f"precheck completion requires PRECHECKING, got {application.status}",
            )
        if str(result.application_id) != str(application.id):
            raise ApplicationError(
                "APPLICATION_PRECHECK_RESULT_MISMATCH",
                "precheck result belongs to a different application",
            )
        target = (
            ApplicationStatus.READY
            if result.overall == PrecheckResultType.PASS
            else ApplicationStatus.DRAFT
        )
        return ApplicationService._set_status(application, target)

    @staticmethod
    @transaction.atomic
    def abort_precheck(application: HrDoubleTeacherApplication) -> HrDoubleTeacherApplication:
        application = ApplicationService._lock(application)
        if application.status == ApplicationStatus.PRECHECKING:
            return ApplicationService._set_status(application, ApplicationStatus.DRAFT)
        return application

    @staticmethod
    def _provider_results_from_package(package) -> dict[str, ProviderEvidenceResult]:
        snapshots = package.source_snapshots_json or {}
        results = {}
        for key, snapshot in snapshots.items():
            if key == "_meta" or not isinstance(snapshot, dict):
                continue
            results[key] = ProviderEvidenceResult(
                status=str(snapshot.get("status", "ERROR")),
                provider_version=str(snapshot.get("providerVersion", "") or ""),
            )
        return results

    @staticmethod
    @transaction.atomic
    def submit(application: HrDoubleTeacherApplication) -> HrDoubleTeacherApplication:
        """Revalidate the generated package, freeze it, then enter SUBMITTED."""
        application = ApplicationService._lock(application)
        if application.status == ApplicationStatus.SUBMITTED:
            return application
        if application.status != ApplicationStatus.READY:
            raise ApplicationError(
                "APPLICATION_NOT_READY",
                f"submission requires READY, got {application.status}",
            )
        ApplicationService._assert_batch_accepts_application(application)

        package = (
            HrDoubleTeacherEvidencePackage.objects.select_for_update()
            .filter(
                application_id=application,
                rule_pack_version_id=application.batch_id.rule_pack_version_id,
                status="GENERATED",
            )
            .order_by("-generated_at", "-id")
            .first()
        )
        if package is None:
            raise ApplicationError(
                "APPLICATION_PRECHECK_PACKAGE_REQUIRED",
                "READY application has no generated evidence package for the frozen rule version",
            )

        provider_results = ApplicationService._provider_results_from_package(package)
        precheck = PrecheckService.precheck(
            application,
            package,
            provider_results=provider_results,
        )
        if precheck.overall != PrecheckResultType.PASS:
            raise ApplicationError(
                "APPLICATION_PRECHECK_NOT_PASS",
                f"submission recheck is {precheck.overall}; rebuild evidence and precheck again",
            )
        try:
            EvidenceAggregationService.freeze_package(package)
        except EvidenceAggregationError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc

        return ApplicationService._set_status(application, ApplicationStatus.SUBMITTED)
