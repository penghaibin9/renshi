"""HR05 formal activation fact correction/revocation authority.

The successful activation snapshot is never edited.  A privileged correction
or revocation appends one sealed amendment under a tenant-scoped row lock and
emits an outbox event in the same transaction.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import transaction
from django.utils import timezone

from hr_onboarding.api.exceptions import (
    Hr05ApiError,
    InvalidStateTransitionError,
    NotFoundError,
    TenantContextRequiredError,
    VersionConflictError,
)
from hr_onboarding.models import (
    HrOnboardingActivationAmendment,
    HrOnboardingActivationSnapshot,
)
from hr_onboarding.services.outbox_service import enqueue_outbox


ACTIVATION_FACT_CORRECTED_EVENT = "ActivationFactCorrected"
ACTIVATION_FACT_REVOKED_EVENT = "ActivationFactRevoked"

_CORRECTABLE_FIELDS = frozenset(
    {
        "activatedAt",
        "staffNo",
        "organizationId",
        "positionId",
        "sourceVersions",
    }
)


def _request_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ActivationFactService:
    def __init__(self, *, tenant_id: int, actor_user_id: int | None = None):
        if not tenant_id:
            raise TenantContextRequiredError()
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @staticmethod
    def _validate_idempotency_key(value: str) -> str:
        key = (value or "").strip()
        if not key:
            raise Hr05ApiError("缺少 Idempotency-Key（写操作必须幂等）")
        if len(key) > 128:
            raise Hr05ApiError("Idempotency-Key 超过 128 字符")
        return key

    @staticmethod
    def _validate_reason(value: str) -> str:
        reason = (value or "").strip()
        if not reason:
            raise Hr05ApiError("正式事实更正/撤销必须填写原因")
        return reason

    @staticmethod
    def _latest(snapshot: HrOnboardingActivationSnapshot):
        return snapshot.amendments.order_by("-sequence_no").first()

    @staticmethod
    def _effective_payload(
        snapshot: HrOnboardingActivationSnapshot,
        latest: HrOnboardingActivationAmendment | None,
    ) -> dict[str, Any]:
        if latest is None:
            return snapshot.canonical_payload()
        return dict(latest.after_snapshot_json or {})

    @staticmethod
    def _assert_parent_chain(snapshot: HrOnboardingActivationSnapshot) -> None:
        case = snapshot.case
        if snapshot.tenant_id != case.tenant_id:
            raise TenantContextRequiredError("激活事实与入职案件学校不一致")
        if snapshot.source_type != case.source_type or snapshot.source_id != case.source_id:
            raise VersionConflictError("激活事实的录用/交接父链与案件不一致")
        if snapshot.hr04_proposed_hire_id != (case.hr04_proposed_hire_id or ""):
            raise VersionConflictError("激活事实的拟录用父链与案件不一致")
        if snapshot.hr04_application_id != (case.hr04_application_id or ""):
            raise VersionConflictError("激活事实的应聘父链与案件不一致")
        person_links = (
            (snapshot.person_id, case.hr03_person_id),
            (snapshot.staff_master_id, case.hr03_staff_master_id),
            (snapshot.employment_id, case.hr03_employment_id),
            (snapshot.assignment_id, case.hr03_assignment_id),
        )
        if any(not left or not right or left != right for left, right in person_links):
            raise VersionConflictError("激活事实的人员/任职父链与案件不一致")

    def get_effective_fact(self, *, snapshot_id) -> dict[str, Any]:
        snapshot = (
            HrOnboardingActivationSnapshot.objects.select_related("case")
            .filter(id=snapshot_id, tenant_id=self.tenant_id)
            .first()
        )
        if snapshot is None:
            raise NotFoundError("激活事实不存在或无权访问")
        latest = self._latest(snapshot)
        return self._serialize(snapshot, latest)

    def list_effective_facts(self):
        """Yield the current view of each tenant fact without rewriting history."""

        snapshots = HrOnboardingActivationSnapshot.objects.filter(
            tenant_id=self.tenant_id
        ).select_related("case")
        for snapshot in snapshots.iterator():
            yield self._serialize(snapshot, self._latest(snapshot))

    def _serialize(self, snapshot, latest) -> dict[str, Any]:
        revoked = bool(
            latest and latest.action == HrOnboardingActivationAmendment.Action.REVOCATION
        )
        return {
            "snapshot_id": str(snapshot.id),
            "case_id": str(snapshot.case_id),
            "tenant_id": snapshot.tenant_id,
            "status": "REVOKED" if revoked else "EFFECTIVE",
            "version": latest.sequence_no + 1 if latest else 1,
            "latest_amendment_id": str(latest.id) if latest else None,
            "payload": self._effective_payload(snapshot, latest),
            "initial_content_hash": snapshot.content_hash,
            "latest_content_hash": latest.content_hash if latest else snapshot.content_hash,
        }

    @transaction.atomic
    def correct(
        self,
        *,
        snapshot_id,
        changes: dict[str, Any],
        reason: str,
        idempotency_key: str,
    ) -> HrOnboardingActivationAmendment:
        return self._append(
            snapshot_id=snapshot_id,
            action=HrOnboardingActivationAmendment.Action.CORRECTION,
            changes=changes,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    @transaction.atomic
    def revoke(
        self,
        *,
        snapshot_id,
        reason: str,
        idempotency_key: str,
    ) -> HrOnboardingActivationAmendment:
        return self._append(
            snapshot_id=snapshot_id,
            action=HrOnboardingActivationAmendment.Action.REVOCATION,
            changes={},
            reason=reason,
            idempotency_key=idempotency_key,
        )

    def _append(self, *, snapshot_id, action, changes, reason, idempotency_key):
        key = self._validate_idempotency_key(idempotency_key)
        reason = self._validate_reason(reason)
        changes = dict(changes or {})
        invalid_fields = sorted(set(changes) - _CORRECTABLE_FIELDS)
        if invalid_fields:
            raise Hr05ApiError(
                "更正包含禁止覆盖的人员/录用父链字段",
                details={"invalidFields": invalid_fields},
            )
        if action == HrOnboardingActivationAmendment.Action.CORRECTION and not changes:
            raise Hr05ApiError("更正内容不能为空")

        request_payload = {
            "tenantId": self.tenant_id,
            "snapshotId": str(snapshot_id),
            "action": action,
            "changes": changes,
            "reason": reason,
        }
        request_hash = _request_hash(request_payload)
        replay = HrOnboardingActivationAmendment.objects.filter(
            tenant_id=self.tenant_id,
            idempotency_key=key,
        ).first()
        if replay is not None:
            if replay.request_hash != request_hash:
                raise VersionConflictError("相同 Idempotency-Key 对应了不同请求")
            return replay

        snapshot = (
            HrOnboardingActivationSnapshot.objects.select_for_update()
            .select_related("case")
            .filter(id=snapshot_id, tenant_id=self.tenant_id)
            .first()
        )
        if snapshot is None:
            raise NotFoundError("激活事实不存在或无权访问")
        self._assert_parent_chain(snapshot)

        # A concurrent retry may have passed the first lookup before this
        # transaction acquired the snapshot lock. Re-check under the lock so
        # the same command never falls through to the unique constraint.
        replay = HrOnboardingActivationAmendment.objects.filter(
            tenant_id=self.tenant_id,
            idempotency_key=key,
        ).first()
        if replay is not None:
            if replay.request_hash != request_hash:
                raise VersionConflictError("相同 Idempotency-Key 对应了不同请求")
            return replay

        latest = self._latest(snapshot)
        if latest and latest.action == HrOnboardingActivationAmendment.Action.REVOCATION:
            raise InvalidStateTransitionError("已撤销的激活事实不能再次更正或撤销")

        before = self._effective_payload(snapshot, latest)
        after = dict(before)
        if action == HrOnboardingActivationAmendment.Action.CORRECTION:
            after.update(changes)
        else:
            after["revoked"] = True
            after["revocationReason"] = reason

        amendment = HrOnboardingActivationAmendment.objects.create(
            tenant_id=self.tenant_id,
            snapshot=snapshot,
            predecessor=latest,
            sequence_no=(latest.sequence_no + 1) if latest else 1,
            action=action,
            idempotency_key=key,
            request_hash=request_hash,
            reason=reason,
            before_snapshot_json=before,
            after_snapshot_json=after,
            actor_user_id=self.actor_user_id,
            effective_at=timezone.now(),
        )
        event_type = (
            ACTIVATION_FACT_CORRECTED_EVENT
            if action == HrOnboardingActivationAmendment.Action.CORRECTION
            else ACTIVATION_FACT_REVOKED_EVENT
        )
        enqueue_outbox(
            tenant_id=self.tenant_id,
            event_type=event_type,
            aggregate_type="HrOnboardingActivationSnapshot",
            aggregate_id=str(snapshot.id),
            correlation_id=str(snapshot.case_id),
            payload={
                "snapshot_id": str(snapshot.id),
                "case_id": str(snapshot.case_id),
                "amendment_id": str(amendment.id),
                "sequence_no": amendment.sequence_no,
                "action": amendment.action,
                "content_hash": amendment.content_hash,
            },
        )
        return amendment
