"""Idempotent daily jobs for canonical HR authority domains.

These jobs deliberately iterate one concrete school at a time.  A failure in
one school is reported after the remaining schools have been attempted, so a
single bad policy cannot silently suppress every other school's governance.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from horilla.horilla_middlewares import tenant_context


logger = logging.getLogger(__name__)


class CanonicalHrJobError(RuntimeError):
    pass


def _tenant_ids():
    from base.models import Company

    return Company.objects.order_by("id").values_list("id", flat=True).iterator()


def anonymize_expired_recruitment_candidates():
    """Apply HR04 retention policy without touching active or legally held cases."""
    from hr_recruitment.constants import CandidateStatus
    from hr_recruitment.models import HrRecruitmentCandidate
    from hr_recruitment.services.retention_service import CandidateRetentionService

    as_of = timezone.localdate()
    failures = []
    for tenant_id in _tenant_ids():
        try:
            due_ids = list(
                HrRecruitmentCandidate.objects.filter(
                    tenant_id=tenant_id,
                    status=CandidateStatus.ACTIVE,
                    legal_hold=False,
                    retention_until__lt=as_of,
                )
                .order_by("retention_until", "id")
                .values_list("id", flat=True)[: settings.CANONICAL_HR_JOB_BATCH_SIZE]
            )
            counts = {"anonymized": 0, "replayed": 0, "blocked": 0}
            service = CandidateRetentionService(tenant_id)
            for candidate_id in due_ids:
                outcome = service.anonymize_if_due(candidate_id, as_of=as_of)
                key = outcome.status if outcome.status in counts else "blocked"
                counts[key] += 1
            if due_ids:
                logger.info(
                    "HR04 retention completed tenant=%s selected=%s anonymized=%s replayed=%s blocked=%s",
                    tenant_id,
                    len(due_ids),
                    counts["anonymized"],
                    counts["replayed"],
                    counts["blocked"],
                )
            if counts["blocked"]:
                raise CanonicalHrJobError(
                    f"{counts['blocked']} expired candidates remain protected by active workflow"
                )
        except Exception as exc:
            logger.exception("HR04 retention failed tenant=%s", tenant_id)
            failures.append(f"tenant={tenant_id}:{type(exc).__name__}")
    if failures:
        raise CanonicalHrJobError("HR04 retention failures: " + ", ".join(failures))


def scan_canonical_contract_expiry():
    """Run HR07's sealed-policy expiry action for every school."""
    from hr_contracts.models import HrContractAgreement
    from hr_contracts.services.alert_escalation import CanonicalContractExpiryService

    as_of = timezone.localdate()
    failures = []
    for tenant_id in _tenant_ids():
        try:
            scannable = HrContractAgreement.objects.filter(
                tenant_id=tenant_id,
                status__in=CanonicalContractExpiryService._SCANNABLE_STATUSES,
            ).count()
            if scannable > settings.CANONICAL_HR_JOB_BATCH_SIZE:
                raise CanonicalHrJobError(
                    f"{scannable} contracts exceed configured scan limit "
                    f"{settings.CANONICAL_HR_JOB_BATCH_SIZE}"
                )
            with tenant_context(tenant_id):
                result = CanonicalContractExpiryService(tenant_id).scan(
                    as_of=as_of,
                    limit=settings.CANONICAL_HR_JOB_BATCH_SIZE,
                )
            if result["blocked"]:
                raise CanonicalHrJobError(
                    f"{result['blocked']} contract expiry decisions were blocked"
                )
            logger.info(
                "canonical HR07 expiry scan completed tenant=%s scanned=%s eligible=%s created=%s replayed=%s",
                tenant_id,
                result["scanned"],
                result["eligible"],
                result["createdRisks"],
                result["replayed"],
            )
        except Exception as exc:
            logger.exception("canonical HR07 expiry scan failed tenant=%s", tenant_id)
            failures.append(f"tenant={tenant_id}:{type(exc).__name__}")
    if failures:
        raise CanonicalHrJobError("HR07 expiry scan failures: " + ", ".join(failures))


def run_canonical_retirement_prechecks():
    """Evaluate active HR03 relationships against versioned HR16 policies.

    The daily idempotency key makes restarts and scheduler retries harmless.
    Raw birth dates are read only inside the HR16 authority service and are
    never placed in scheduler logs or event payloads.
    """
    from hr_exit.models import RetirementPolicy
    from hr_exit.services.retirement_policy_service import RetirementPrecheckService
    from hr_staff.constants import RelationshipStatus
    from hr_staff.models import HrEmploymentRelationship

    as_of = timezone.localdate()
    failures = []
    for tenant_id in _tenant_ids():
        try:
            relationship_count = (
                HrEmploymentRelationship.objects.filter(
                    tenant_id=tenant_id,
                    status=RelationshipStatus.ACTIVE,
                    effective_from__lte=as_of,
                )
                .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
                .count()
            )
            if relationship_count == 0:
                logger.info(
                    "canonical HR16 retirement precheck skipped tenant=%s relationships=0",
                    tenant_id,
                )
                continue
            if relationship_count > settings.CANONICAL_HR_JOB_BATCH_SIZE:
                raise CanonicalHrJobError(
                    f"{relationship_count} relationships exceed configured precheck limit "
                    f"{settings.CANONICAL_HR_JOB_BATCH_SIZE}"
                )
            has_policy = RetirementPolicy.objects.filter(
                tenant_id=tenant_id,
                status=RetirementPolicy.Status.ACTIVE,
                effective_from__lte=as_of,
            ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of)).exists()
            if not has_policy:
                raise CanonicalHrJobError("no active HR16 retirement policy")
            relationships = (
                HrEmploymentRelationship.objects.filter(
                    tenant_id=tenant_id,
                    status=RelationshipStatus.ACTIVE,
                    effective_from__lte=as_of,
                )
                .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
                .order_by("id")
                .values_list("id", "staff_id__person_id")
                .iterator(chunk_size=settings.CANONICAL_HR_JOB_BATCH_SIZE)
            )
            counts = {"created": 0, "replayed": 0, "manual": 0}
            with tenant_context(tenant_id):
                service = RetirementPrecheckService(tenant_id)
                for relationship_id, person_id in relationships:
                    result = service.evaluate(
                        person_id=person_id,
                        employment_relationship_id=relationship_id,
                        as_of=as_of,
                        idempotency_key=f"scheduled:{as_of.isoformat()}:{relationship_id}",
                    )
                    counts["created" if result.created else "replayed"] += 1
                    if result.precheck.decision == result.precheck.Decision.MANUAL_REVIEW:
                        counts["manual"] += 1
            logger.info(
                "canonical HR16 retirement precheck completed tenant=%s relationships=%s created=%s replayed=%s manual=%s",
                tenant_id,
                counts["created"] + counts["replayed"],
                counts["created"],
                counts["replayed"],
                counts["manual"],
            )
        except Exception as exc:
            logger.exception("canonical HR16 retirement precheck failed tenant=%s", tenant_id)
            failures.append(f"tenant={tenant_id}:{type(exc).__name__}")
    if failures:
        raise CanonicalHrJobError("HR16 retirement precheck failures: " + ", ".join(failures))


def dispatch_external_access_provisioning():
    """Drain HR08 IAM grant/revoke requests for every concrete school."""
    from hr_external.services.provisioning_dispatch_service import (
        ProvisioningDispatchService,
    )

    failures = []
    for tenant_id in _tenant_ids():
        try:
            summary = ProvisioningDispatchService().dispatch_batch(
                tenant_id=tenant_id, limit=500
            )
            if summary["selected"]:
                logger.info(
                    "HR08 IAM dispatch completed tenant=%s selected=%s succeeded=%s retrying=%s failed=%s skipped=%s",
                    tenant_id, summary["selected"], summary["succeeded"],
                    summary["retrying"], summary["failed"], summary["skipped"],
                )
            if summary["failed"]:
                raise CanonicalHrJobError(
                    f"{summary['failed']} IAM requests failed terminally"
                )
        except Exception as exc:
            logger.exception("HR08 IAM dispatch failed tenant=%s", tenant_id)
            failures.append(f"tenant={tenant_id}:{type(exc).__name__}")
    if failures:
        raise CanonicalHrJobError("HR08 IAM dispatch failures: " + ", ".join(failures))


def dispatch_external_academic_provisioning():
    """Drain HR08 academic identity activation/deactivation requests."""
    from hr_external.services.academic_identity_service import AcademicIdentityService

    failures = []
    for tenant_id in _tenant_ids():
        try:
            summary = AcademicIdentityService().dispatch_batch(
                tenant_id=tenant_id, limit=500
            )
            if summary["selected"]:
                logger.info(
                    "HR08 academic dispatch completed tenant=%s selected=%s succeeded=%s retrying=%s failed=%s skipped=%s",
                    tenant_id,
                    summary["selected"],
                    summary["succeeded"],
                    summary["retrying"],
                    summary["failed"],
                    summary["skipped"],
                )
            if summary["failed"]:
                raise CanonicalHrJobError(
                    f"{summary['failed']} academic requests failed terminally"
                )
        except Exception as exc:
            logger.exception("HR08 academic dispatch failed tenant=%s", tenant_id)
            failures.append(f"tenant={tenant_id}:{type(exc).__name__}")
    if failures:
        raise CanonicalHrJobError(
            "HR08 academic dispatch failures: " + ", ".join(failures)
        )


def run_external_import_jobs():
    """Execute confirmed HR08 imports instead of leaving them in COMMITTING."""
    from hr_external.constants import ExternalImportJobStatus
    from hr_external.models import HrExternalImportJob
    from hr_external.services.import_service import ImportService

    failures = []
    for tenant_id in _tenant_ids():
        try:
            job_ids = list(
                HrExternalImportJob.objects.filter(
                    tenant_id=tenant_id,
                    status=ExternalImportJobStatus.COMMITTING,
                )
                .order_by("created_at", "id")
                .values_list("id", flat=True)[:10]
            )
            for job_id in job_ids:
                job = HrExternalImportJob.objects.filter(
                    tenant_id=tenant_id, id=job_id
                ).first()
                if job is not None:
                    ImportService().execute_commit(job, tenant_id=tenant_id)
            if job_ids:
                logger.info(
                    "HR08 import runner completed tenant=%s jobs=%s",
                    tenant_id,
                    len(job_ids),
                )
        except Exception as exc:
            logger.exception("HR08 import runner failed tenant=%s", tenant_id)
            failures.append(f"tenant={tenant_id}:{type(exc).__name__}")
    if failures:
        raise CanonicalHrJobError("HR08 import failures: " + ", ".join(failures))


def expire_external_engagements():
    """Expire ended HR08 terms and enqueue all access revocations."""
    from django.db import transaction

    from hr_external.constants import ExternalEngagementStatus
    from hr_external.models import HrExternalEngagement, HrExternalLifecycleEvent
    from hr_external.services.access_service import AccessService

    as_of = timezone.localdate()
    expirable = (
        ExternalEngagementStatus.ACTIVE,
        ExternalEngagementStatus.REVIEW_DUE,
        ExternalEngagementStatus.RENEWAL_IN_PROGRESS,
        ExternalEngagementStatus.SUSPENDED,
    )
    failures = []
    for tenant_id in _tenant_ids():
        try:
            expirable_count = HrExternalEngagement.objects.filter(
                tenant_id=tenant_id,
                status__in=expirable,
                end_at__isnull=False,
                end_at__lte=as_of,
            ).count()
            if expirable_count > settings.CANONICAL_HR_JOB_BATCH_SIZE:
                raise CanonicalHrJobError(
                    f"{expirable_count} engagements exceed configured expiry limit "
                    f"{settings.CANONICAL_HR_JOB_BATCH_SIZE}"
                )
            ids = list(
                HrExternalEngagement.objects.filter(
                    tenant_id=tenant_id,
                    status__in=expirable,
                    end_at__isnull=False,
                    end_at__lte=as_of,
                )
                .order_by("end_at", "id")
                .values_list("id", flat=True)[: settings.CANONICAL_HR_JOB_BATCH_SIZE]
            )
            for engagement_id in ids:
                with transaction.atomic(), tenant_context(tenant_id):
                    engagement = (
                        HrExternalEngagement.objects.select_for_update()
                        .filter(
                            tenant_id=tenant_id,
                            id=engagement_id,
                            status__in=expirable,
                            end_at__lte=as_of,
                        )
                        .first()
                    )
                    if engagement is None:
                        continue
                    engagement.status = ExternalEngagementStatus.EXPIRED
                    engagement.version += 1
                    engagement.save(update_fields=["status", "version", "updated_at"])
                    AccessService().revoke_engagement_access(
                        tenant_id=tenant_id, engagement=engagement
                    )
                    HrExternalLifecycleEvent.objects.get_or_create(
                        tenant_id=tenant_id,
                        idempotency_key=f"expire:{engagement.id}:{engagement.end_at.isoformat()}",
                        defaults={
                            "event_type": "ExternalEngagementExpired",
                            "event_version": 1,
                            "aggregate_type": "ExternalEngagement",
                            "aggregate_id": engagement.id,
                            "aggregate_version": engagement.version,
                            "engagement_id": engagement,
                            "payload_json": {
                                "engagementId": str(engagement.id),
                                "endAt": engagement.end_at.isoformat(),
                            },
                            "status": "PUBLISHED",
                        },
                    )
            if ids:
                logger.info(
                    "HR08 engagement expiry completed tenant=%s expired=%s",
                    tenant_id,
                    len(ids),
                )
        except Exception as exc:
            logger.exception("HR08 engagement expiry failed tenant=%s", tenant_id)
            failures.append(f"tenant={tenant_id}:{type(exc).__name__}")
    if failures:
        raise CanonicalHrJobError("HR08 expiry failures: " + ", ".join(failures))
