"""HR06 correction workflow backed by HR03's formal Authority provider."""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from hr_changes.authority_registry import EVENT_CHANGE_APPLY_FAILED, EVENT_CHANGE_CORRECTED
from hr_changes.constants import CaseStatus
from hr_changes.integrations.outbox import enqueue_outbox
from hr_changes.models import (
    HrChangeCorrection,
    HrChangeEffectiveSnapshot,
    HrChangeTransition,
    HrPersonnelChangeCase,
)
from hr_changes.providers.hr03_correction import (
    HR03CorrectionProvider,
    HR03CorrectionProviderError,
)
from hr_changes.services.state_machine import transition


class CorrectionServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class CorrectionService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    def _get_case_or_deny(self, case_id, *, lock: bool = False) -> HrPersonnelChangeCase:
        query = HrPersonnelChangeCase.objects
        if lock:
            query = query.select_for_update()
        case = query.select_related("staff_master_id__person_id").filter(
            tenant_id=self.tenant_id, id=case_id
        ).first()
        if case is None:
            raise CorrectionServiceError("CHANGE_NOT_FOUND", "异动案件不存在")
        return case

    def _get_correction_or_deny(self, correction_id) -> HrChangeCorrection:
        correction = (
            HrChangeCorrection.objects.select_for_update()
            .select_related("change_case_id__staff_master_id__person_id")
            .filter(tenant_id=self.tenant_id, id=correction_id)
            .first()
        )
        if correction is None:
            raise CorrectionServiceError("CHANGE_NOT_FOUND", "纠错记录不存在")
        return correction

    @staticmethod
    def _assert_version(correction: HrChangeCorrection, expected_version: int | None):
        if expected_version is None:
            raise CorrectionServiceError("VERSION_REQUIRED", "必须提供 If-Match/version")
        if correction.version != expected_version:
            raise CorrectionServiceError("VERSION_CONFLICT", "纠错版本已变化，请刷新后重试")

    @staticmethod
    def _request_hash(
        *, case_id, correction_type, items, reason, authority_version, evidence_material_id
    ) -> str:
        payload = {
            "caseId": str(case_id),
            "correctionType": correction_type,
            "items": items,
            "reason": reason,
            "authorityVersion": authority_version,
            "evidenceMaterialId": str(evidence_material_id or ""),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    @transaction.atomic
    def create_correction(
        self,
        *,
        case_id,
        correction_type: str,
        requested_values: dict,
        reason: str,
        authority_version: int,
        idempotency_key: str,
        case_version: int | None = None,
        evidence_material_id=None,
    ) -> HrChangeCorrection:
        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key:
            raise CorrectionServiceError("IDEMPOTENCY_KEY_REQUIRED", "必须提供 Idempotency-Key")
        if len(idempotency_key) > 64:
            raise CorrectionServiceError("IDEMPOTENCY_KEY_INVALID", "Idempotency-Key 最长 64 字符")
        if not str(reason or "").strip():
            raise CorrectionServiceError("CHANGE_CORRECTION_REASON_REQUIRED", "纠错原因不能为空")

        provider = HR03CorrectionProvider(self.tenant_id, self.actor_user_id)
        try:
            items = provider.normalize_requested_values(requested_values)
        except HR03CorrectionProviderError as exc:
            raise CorrectionServiceError(exc.code, exc.message) from exc
        request_hash = self._request_hash(
            case_id=case_id,
            correction_type=correction_type,
            items=items,
            reason=reason,
            authority_version=authority_version,
            evidence_material_id=evidence_material_id,
        )
        existing = HrChangeCorrection.objects.select_for_update().filter(
            tenant_id=self.tenant_id, create_idempotency_key=idempotency_key
        ).first()
        if existing:
            if existing.create_request_hash != request_hash:
                raise CorrectionServiceError(
                    "IDEMPOTENCY_KEY_CONFLICT", "该 Idempotency-Key 已用于不同纠错请求"
                )
            return existing

        case = self._get_case_or_deny(case_id, lock=True)
        if case.status != CaseStatus.EFFECTIVE:
            raise CorrectionServiceError("CHANGE_INVALID_STATE", "仅已生效案件可纠错")
        if case_version is not None and case.version != case_version:
            raise CorrectionServiceError("VERSION_CONFLICT", "异动案件版本已变化，请刷新后重试")
        try:
            prepared = provider.prepare(
                staff=case.staff_master_id,
                requested_values={"items": items},
                authority_version=int(authority_version),
            )
        except (TypeError, ValueError):
            raise CorrectionServiceError(
                "AUTHORITY_VERSION_REQUIRED", "authorityVersion 必须是整数"
            ) from None
        except HR03CorrectionProviderError as exc:
            raise CorrectionServiceError(exc.code, exc.message) from exc

        snapshot = HrChangeEffectiveSnapshot.objects.filter(change_case_id=case).first()
        return HrChangeCorrection.objects.create(
            tenant_id=self.tenant_id,
            change_case_id=case,
            correction_type=correction_type,
            requested_values_json={"items": prepared.items},
            reason=str(reason).strip(),
            requested_by=self.actor_user_id,
            previous_snapshot_hash=snapshot.checksum if snapshot else "",
            authority_version=int(authority_version),
            authority_snapshot_hash=prepared.authority_snapshot_hash,
            provider_code=provider.provider_code,
            evidence_material_id=evidence_material_id,
            create_idempotency_key=idempotency_key,
            create_request_hash=request_hash,
        )

    @transaction.atomic
    def submit(self, correction_id, *, expected_version: int | None = None) -> HrChangeCorrection:
        correction = self._get_correction_or_deny(correction_id)
        if expected_version is not None:
            self._assert_version(correction, expected_version)
        if correction.status != HrChangeCorrection.Status.DRAFT:
            raise CorrectionServiceError("CHANGE_INVALID_STATE", "仅草稿纠错可提交")
        correction.status = HrChangeCorrection.Status.SUBMITTED
        correction.version += 1
        correction.save(update_fields=["status", "version", "updated_at"])
        return correction

    @transaction.atomic
    def approve(self, correction_id, *, comment: str = "", expected_version: int | None = None) -> HrChangeCorrection:
        correction = self._get_correction_or_deny(correction_id)
        if expected_version is not None:
            self._assert_version(correction, expected_version)
        if correction.status != HrChangeCorrection.Status.SUBMITTED:
            raise CorrectionServiceError("CHANGE_INVALID_STATE", "仅已提交纠错可批准")
        correction.status = HrChangeCorrection.Status.APPROVED
        correction.approved_by = self.actor_user_id
        correction.version += 1
        correction.save(update_fields=["status", "approved_by", "version", "updated_at"])
        return correction

    @transaction.atomic
    def reject(self, correction_id, *, comment: str = "", expected_version: int | None = None) -> HrChangeCorrection:
        correction = self._get_correction_or_deny(correction_id)
        if expected_version is not None:
            self._assert_version(correction, expected_version)
        if correction.status != HrChangeCorrection.Status.SUBMITTED:
            raise CorrectionServiceError("CHANGE_INVALID_STATE", "仅已提交纠错可驳回")
        correction.status = HrChangeCorrection.Status.REJECTED
        correction.version += 1
        correction.save(update_fields=["status", "version", "updated_at"])
        return correction

    def apply(
        self,
        correction_id,
        *,
        expected_version: int | None,
        idempotency_key: str,
    ) -> HrChangeCorrection:
        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key:
            raise CorrectionServiceError("IDEMPOTENCY_KEY_REQUIRED", "必须提供 Idempotency-Key")
        if len(idempotency_key) > 64:
            raise CorrectionServiceError("IDEMPOTENCY_KEY_INVALID", "Idempotency-Key 最长 64 字符")

        correction = None
        try:
            with transaction.atomic():
                correction = self._get_correction_or_deny(correction_id)
                if correction.status == HrChangeCorrection.Status.APPLIED:
                    if correction.apply_idempotency_key == idempotency_key:
                        return correction
                    raise CorrectionServiceError(
                        "IDEMPOTENCY_KEY_CONFLICT", "纠错已由另一 Idempotency-Key 应用"
                    )
                self._assert_version(correction, expected_version)
                if correction.status not in (
                    HrChangeCorrection.Status.APPROVED,
                    HrChangeCorrection.Status.FAILED,
                ):
                    raise CorrectionServiceError(
                        "CHANGE_CORRECTION_REQUIRES_APPROVAL", "纠错必须先审批"
                    )
                if correction.apply_idempotency_key and correction.apply_idempotency_key != idempotency_key:
                    raise CorrectionServiceError(
                        "IDEMPOTENCY_KEY_CONFLICT", "失败重试必须复用原 Idempotency-Key"
                    )

                correction.status = HrChangeCorrection.Status.APPLYING
                correction.apply_idempotency_key = idempotency_key
                correction.apply_error = ""
                correction.save(
                    update_fields=["status", "apply_idempotency_key", "apply_error", "updated_at"]
                )

                receipt = HR03CorrectionProvider(
                    self.tenant_id, self.actor_user_id
                ).apply(
                    correction=correction,
                    evidence_material_id=correction.evidence_material_id,
                )
                new_hash = receipt.authority_snapshot_hash
                correction.provider_case_id = receipt.provider_case_id
                correction.provider_case_version = receipt.provider_case_version
                correction.applied_fields_json = receipt.applied_fields
                correction.new_snapshot_hash = new_hash
                correction.status = HrChangeCorrection.Status.APPLIED
                correction.applied_at = timezone.now()
                correction.version += 1
                correction.save(
                    update_fields=[
                        "provider_case_id",
                        "provider_case_version",
                        "applied_fields_json",
                        "new_snapshot_hash",
                        "status",
                        "applied_at",
                        "version",
                        "updated_at",
                    ]
                )

                case = self._get_case_or_deny(correction.change_case_id_id, lock=True)
                from_status = case.status
                target = transition("correct", case.status, CaseStatus.CORRECTED)
                case.status = target
                case.version += 1
                case.save(update_fields=["status", "version", "updated_at"])
                HrChangeTransition.objects.create(
                    change_case_id=case,
                    tenant_id=self.tenant_id,
                    from_status=from_status,
                    to_status=target,
                    action="correct",
                    actor_id=self.actor_user_id,
                    comment=f"HR03正式纠错已应用 providerCase={receipt.provider_case_id}",
                    request_id=idempotency_key,
                    snapshot_hash=new_hash,
                )
                enqueue_outbox(
                    tenant_id=self.tenant_id,
                    event_type=EVENT_CHANGE_CORRECTED,
                    aggregate_type="personnel_change",
                    aggregate_id=str(case.id),
                    correlation_id=idempotency_key,
                    event_id=f"hr06-correction-{correction.id}-applied",
                    payload={
                        "changeCaseId": str(case.id),
                        "correctionId": str(correction.id),
                        "staffId": str(case.staff_master_id_id),
                        "provider": receipt.provider_case_id,
                        "changedFields": receipt.applied_fields,
                        "eventVersion": 1,
                    },
                )
                return correction
        except CorrectionServiceError:
            raise
        except Exception as exc:
            code = getattr(exc, "code", "CHANGE_CORRECTION_APPLY_FAILED")
            message = getattr(exc, "message", str(exc))
            if correction is not None:
                self._record_failure(correction.id, idempotency_key, code, message)
            raise CorrectionServiceError(code, message) from exc

    def _record_failure(self, correction_id, idempotency_key: str, code: str, message: str):
        with transaction.atomic():
            correction = self._get_correction_or_deny(correction_id)
            if correction.status == HrChangeCorrection.Status.APPLIED:
                return
            correction.status = HrChangeCorrection.Status.FAILED
            correction.apply_idempotency_key = idempotency_key
            correction.apply_error = f"{code}: {message}"[:2000]
            correction.version = F("version") + 1
            correction.save(
                update_fields=[
                    "status",
                    "apply_idempotency_key",
                    "apply_error",
                    "version",
                    "updated_at",
                ]
            )
            correction.refresh_from_db()
            case = correction.change_case_id
            HrChangeTransition.objects.create(
                change_case_id=case,
                tenant_id=self.tenant_id,
                from_status=case.status,
                to_status=case.status,
                action="correction_apply_failed",
                actor_id=self.actor_user_id,
                comment=f"{code}: {message}"[:1000],
                request_id=idempotency_key,
            )
            enqueue_outbox(
                tenant_id=self.tenant_id,
                event_type=EVENT_CHANGE_APPLY_FAILED,
                aggregate_type="personnel_change",
                aggregate_id=str(case.id),
                correlation_id=idempotency_key,
                event_id=f"hr06-correction-{correction.id}-failed-v{correction.version}",
                payload={
                    "changeCaseId": str(case.id),
                    "correctionId": str(correction.id),
                    "errorCode": code,
                    "eventVersion": 1,
                },
            )
