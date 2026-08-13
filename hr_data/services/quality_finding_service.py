"""Governance lifecycle for HR18 data-quality findings.

Acknowledgement is a human workflow decision.  ``FIXED_AT_SOURCE`` is stricter:
HR18 must rerun the original quality rule against the current source Authority
and may close the finding only when that verification run is fully successful
and the original immutable finding fingerprint is absent.

Historical/as-of findings are evidence about a past cut and are therefore never
rewritten as "fixed" by a later current-state repair.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_data.models import DataQualityFinding, DataQualityRun
from hr_data.services.quality_runtime_service import RuntimeDataQualityExecutionService
from hr_data.services.quality_service import DataQualityError


class DataQualityFindingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class FindingVerificationResult:
    finding: DataQualityFinding
    verification_run: Optional[DataQualityRun]
    changed: bool


class DataQualityFindingService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise DataQualityFindingError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock(self, finding_id) -> DataQualityFinding:
        finding = (
            DataQualityFinding.objects.select_for_update()
            .filter(id=finding_id, tenant_id=self.tenant_id)
            .first()
        )
        if finding is None:
            raise DataQualityFindingError(
                "QUALITY_FINDING_NOT_FOUND", "quality finding not found"
            )
        return finding

    @transaction.atomic
    def acknowledge(self, finding_id) -> DataQualityFinding:
        finding = self._lock(finding_id)
        if finding.status == DataQualityFinding.Status.ACKNOWLEDGED:
            return finding
        if finding.status != DataQualityFinding.Status.OPEN:
            raise DataQualityFindingError(
                "QUALITY_FINDING_INVALID_STATE",
                f"finding status {finding.status} cannot be acknowledged",
            )
        finding.status = DataQualityFinding.Status.ACKNOWLEDGED
        finding.updated_by = self.actor_user_id
        finding.save(update_fields=["status", "updated_by", "updated_at"])
        return finding

    def _original_run(self, finding: DataQualityFinding) -> DataQualityRun:
        if not finding.quality_run_id:
            raise DataQualityFindingError(
                "QUALITY_FINDING_RUN_REQUIRED",
                "finding is not linked to a quality execution run",
            )
        run = DataQualityRun.objects.filter(
            id=finding.quality_run_id,
            tenant_id=self.tenant_id,
        ).first()
        if run is None:
            raise DataQualityFindingError(
                "QUALITY_FINDING_RUN_NOT_FOUND",
                "finding quality execution run is missing from the current tenant",
            )
        return run

    def verify_fixed(
        self,
        finding_id,
        *,
        verification_run_no: str,
    ) -> FindingVerificationResult:
        """Verify a current-state finding disappeared before marking it fixed.

        Provider execution intentionally happens outside the row-lock transaction;
        after it completes we re-lock the finding and re-check immutable identity
        before applying the lifecycle transition.
        """
        finding = DataQualityFinding.objects.filter(
            id=finding_id,
            tenant_id=self.tenant_id,
        ).first()
        if finding is None:
            raise DataQualityFindingError(
                "QUALITY_FINDING_NOT_FOUND", "quality finding not found"
            )
        if finding.status == DataQualityFinding.Status.FIXED_AT_SOURCE:
            return FindingVerificationResult(finding, None, False)
        if finding.status not in {
            DataQualityFinding.Status.OPEN,
            DataQualityFinding.Status.ACKNOWLEDGED,
        }:
            raise DataQualityFindingError(
                "QUALITY_FINDING_INVALID_STATE",
                f"finding status {finding.status} cannot be verified as fixed",
            )

        original_run = self._original_run(finding)
        if original_run.as_of_date is not None:
            raise DataQualityFindingError(
                "QUALITY_HISTORICAL_FINDING_IMMUTABLE",
                "historical as-of findings cannot be rewritten as fixed by current-state repair",
            )
        if not finding.rule_code or not finding.rule_version:
            raise DataQualityFindingError(
                "QUALITY_FINDING_RULE_REQUIRED",
                "finding is missing its frozen rule identity",
            )

        verification_run_no = str(verification_run_no or "").strip()
        if not verification_run_no:
            raise DataQualityFindingError(
                "QUALITY_VERIFICATION_RUN_NO_REQUIRED",
                "verification_run_no is required",
            )
        if verification_run_no == original_run.run_no:
            raise DataQualityFindingError(
                "QUALITY_VERIFICATION_RUN_REUSE_FORBIDDEN",
                "verification must use a new quality run identity",
            )

        try:
            verification = RuntimeDataQualityExecutionService(
                self.tenant_id,
                actor_user_id=self.actor_user_id,
            ).execute(
                run_no=verification_run_no,
                rule_code=finding.rule_code,
                rule_version=finding.rule_version,
                as_of_date=None,
            )
        except DataQualityError as exc:
            raise DataQualityFindingError(exc.code, str(exc)) from exc

        if verification.run.status != DataQualityRun.Status.SUCCESS:
            raise DataQualityFindingError(
                "QUALITY_FIX_VERIFICATION_INCOMPLETE",
                f"verification run status {verification.run.status} cannot prove a source fix",
            )
        if any(
            item.finding_fingerprint == finding.finding_fingerprint
            for item in verification.findings
        ):
            raise DataQualityFindingError(
                "QUALITY_FINDING_STILL_PRESENT",
                "the source Authority still reports the same finding fingerprint",
            )

        with transaction.atomic():
            locked = self._lock(finding_id)
            if locked.status == DataQualityFinding.Status.FIXED_AT_SOURCE:
                return FindingVerificationResult(locked, verification.run, False)
            if locked.status not in {
                DataQualityFinding.Status.OPEN,
                DataQualityFinding.Status.ACKNOWLEDGED,
            }:
                raise DataQualityFindingError(
                    "QUALITY_FINDING_INVALID_STATE",
                    f"finding status {locked.status} cannot be verified as fixed",
                )
            if (
                locked.finding_fingerprint != finding.finding_fingerprint
                or locked.rule_code != finding.rule_code
                or locked.rule_version != finding.rule_version
                or locked.quality_run_id != finding.quality_run_id
            ):
                raise DataQualityFindingError(
                    "QUALITY_FINDING_IDENTITY_CHANGED",
                    "finding identity changed during source verification",
                )
            locked.status = DataQualityFinding.Status.FIXED_AT_SOURCE
            locked.resolved_at = timezone.now()
            locked.updated_by = self.actor_user_id
            locked.save(
                update_fields=[
                    "status",
                    "resolved_at",
                    "updated_by",
                    "updated_at",
                ]
            )
            return FindingVerificationResult(locked, verification.run, True)
