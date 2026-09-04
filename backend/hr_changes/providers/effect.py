"""Trusted HR02/HR03 execution provider boundary for HR06 effects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date

from hr_changes.constants import ChangeActionCode


class EffectProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class TrustedEffectReceipt:
    provider_code: str
    tenant_id: int
    case_id: str
    case_version: int
    staff_id: str
    action_code: str
    effective_at: date
    approval_snapshot_id: str
    approval_snapshot_hash: str
    idempotency_key: str
    source_fact_ids: list[str]
    target_fact_ids: list[str]
    position_changes: dict
    followup: list
    content_hash: str

    def payload(self) -> dict:
        return {
            "providerCode": self.provider_code,
            "tenantId": int(self.tenant_id),
            "caseId": str(self.case_id),
            "caseVersion": int(self.case_version),
            "staffId": str(self.staff_id),
            "actionCode": self.action_code,
            "effectiveAt": self.effective_at.isoformat(),
            "approvalSnapshotId": str(self.approval_snapshot_id),
            "approvalSnapshotHash": self.approval_snapshot_hash,
            "idempotencyKey": self.idempotency_key,
            "sourceFactIds": list(self.source_fact_ids),
            "targetFactIds": list(self.target_fact_ids),
            "positionChanges": dict(self.position_changes),
            "followup": list(self.followup),
        }

    @classmethod
    def issue(cls, **kwargs):
        receipt = cls(content_hash="", **kwargs)
        receipt.content_hash = _hash(receipt.payload())
        return receipt

    def verify(self, **expected) -> None:
        observed = {
            "tenant_id": int(self.tenant_id),
            "case_id": str(self.case_id),
            "case_version": int(self.case_version),
            "staff_id": str(self.staff_id),
            "action_code": self.action_code,
            "effective_at": self.effective_at,
            "approval_snapshot_id": str(self.approval_snapshot_id),
            "approval_snapshot_hash": self.approval_snapshot_hash,
            "idempotency_key": self.idempotency_key,
        }
        normalized = dict(expected)
        for key in ("case_id", "staff_id", "approval_snapshot_id"):
            normalized[key] = str(normalized[key])
        normalized["tenant_id"] = int(normalized["tenant_id"])
        normalized["case_version"] = int(normalized["case_version"])
        if (
            observed != normalized
            or not self.provider_code
            or not self.source_fact_ids
            or not self.target_fact_ids
            or len(self.approval_snapshot_hash) != 64
            or self.content_hash != _hash(self.payload())
        ):
            raise EffectProviderError(
                "CHANGE_EFFECT_RECEIPT_INVALID",
                "trusted provider receipt is missing, mismatched, or tampered",
            )


class EffectProviderRegistry:
    def __init__(self):
        self._providers = {}

    def register(self, action_codes, provider) -> None:
        if provider is None or not callable(getattr(provider, "execute", None)):
            raise EffectProviderError(
                "CHANGE_EFFECT_PROVIDER_INVALID", "provider must expose execute()"
            )
        for action_code in action_codes:
            self._providers[str(action_code)] = provider

    def require(self, action_code):
        provider = self._providers.get(str(action_code))
        if provider is None:
            raise EffectProviderError(
                "CHANGE_EFFECT_PROVIDER_UNAVAILABLE",
                f"no trusted execution provider for {action_code}",
            )
        return provider


class CanonicalHr02Hr03EffectProvider:
    provider_code = "HR06_CANONICAL_HR02_HR03_V1"

    def execute(
        self,
        *,
        executor,
        case,
        effective_at,
        case_version,
        approval_snapshot_id,
        approval_snapshot_hash,
        idempotency_key,
    ) -> TrustedEffectReceipt:
        result = executor(case, effective_at)
        if not isinstance(result, dict):
            raise EffectProviderError(
                "CHANGE_EFFECT_PROVIDER_INVALID", "provider returned no structured result"
            )
        self._verify_authority_facts(case, result)
        receipt = TrustedEffectReceipt.issue(
            provider_code=self.provider_code,
            tenant_id=case.tenant_id,
            case_id=case.id,
            case_version=case_version,
            staff_id=case.staff_master_id_id,
            action_code=case.action_id.code,
            effective_at=effective_at,
            approval_snapshot_id=approval_snapshot_id,
            approval_snapshot_hash=approval_snapshot_hash,
            idempotency_key=idempotency_key,
            source_fact_ids=list(result.get("source_fact_ids") or []),
            target_fact_ids=list(result.get("target_fact_ids") or []),
            position_changes=dict(result.get("position_changes") or {}),
            followup=list(result.get("followup") or []),
        )
        receipt.verify(
            tenant_id=case.tenant_id,
            case_id=case.id,
            case_version=case_version,
            staff_id=case.staff_master_id_id,
            action_code=case.action_id.code,
            effective_at=effective_at,
            approval_snapshot_id=approval_snapshot_id,
            approval_snapshot_hash=approval_snapshot_hash,
            idempotency_key=idempotency_key,
        )
        return receipt

    @staticmethod
    def _verify_authority_facts(case, result) -> None:
        from hr_staff.models import (
            HrEmploymentRelationship,
            HrStaffAssignment,
            HrStaffMaster,
        )
        from hr_structure.models import HrPositionReservation

        targets = list(result.get("target_fact_ids") or [])
        if not targets:
            raise EffectProviderError(
                "CHANGE_EFFECT_PROVIDER_PARTIAL",
                "provider produced no authoritative target fact",
            )
        for token in targets:
            value = str(token)
            valid = False
            if value.startswith("position-reservation:"):
                valid = HrPositionReservation.objects.filter(
                    tenant_id=case.tenant_id,
                    id=value.split(":", 1)[1],
                    source_business_id=str(case.id),
                    status=HrPositionReservation.Status.COMMITTED,
                ).exists()
            elif value.startswith("staff:"):
                parts = value.split(":")
                version = parts[2].removeprefix("v") if len(parts) == 3 else -1
                valid = HrStaffMaster.objects.filter(
                    tenant_id=case.tenant_id,
                    id=parts[1],
                    version=version,
                ).exists()
            elif value.startswith("relationship:"):
                parts = value.split(":")
                version = parts[2].removeprefix("v") if len(parts) == 3 else -1
                valid = HrEmploymentRelationship.objects.filter(
                    tenant_id=case.tenant_id,
                    id=parts[1],
                    staff_id=case.staff_master_id_id,
                    version=version,
                ).exists()
            elif value.startswith("temporary-link:"):
                from hr_changes.models import HrTemporaryAssignmentLink

                valid = HrTemporaryAssignmentLink.objects.filter(
                    tenant_id=case.tenant_id,
                    id=value.split(":", 1)[1],
                    change_case_id=case,
                ).exists()
            else:
                assignment_id = (
                    value.split(":", 1)[1]
                    if value.startswith("assignment:")
                    else value
                )
                valid = HrStaffAssignment.objects.filter(
                    tenant_id=case.tenant_id,
                    id=assignment_id,
                    employment_relationship_id__staff_id=case.staff_master_id_id,
                ).exists()
            if not valid:
                raise EffectProviderError(
                    "CHANGE_EFFECT_RECEIPT_INVALID",
                    f"provider target fact is missing or crosses tenant: {value}",
                )


SUPPORTED_EFFECT_ACTIONS = frozenset(
    {
        ChangeActionCode.ORG_TRANSFER,
        ChangeActionCode.POSITION_TRANSFER,
        ChangeActionCode.ORG_POSITION_TRANSFER,
        ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH,
        ChangeActionCode.ADD_SECONDARY_ASSIGNMENT,
        ChangeActionCode.END_SECONDARY_ASSIGNMENT,
        ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE,
        ChangeActionCode.EMPLOYMENT_TYPE_CHANGE,
        ChangeActionCode.MANAGER_CHANGE,
        ChangeActionCode.POST_CATEGORY_CHANGE,
        ChangeActionCode.LOCATION_CHANGE,
        ChangeActionCode.TEMPORARY_SECONDMENT,
        ChangeActionCode.TEMPORARY_ATTACHMENT,
        ChangeActionCode.RETURN_FROM_TEMPORARY,
    }
)


def build_default_effect_provider_registry() -> EffectProviderRegistry:
    registry = EffectProviderRegistry()
    registry.register(SUPPORTED_EFFECT_ACTIONS, CanonicalHr02Hr03EffectProvider())
    return registry
