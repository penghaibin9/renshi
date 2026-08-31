"""Append and read HR06 authority-boundary receipts."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from hr_changes.models import (
    HrChangeAuthorityReceipt,
    HrChangeCorrection,
    HrChangeRescind,
    HrPersonnelChangeCase,
)


class AuthorityReceiptError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class AuthorityReceiptService:
    def __init__(self, tenant_id: int):
        self.tenant_id = int(tenant_id)

    def _case(self, case_id):
        case = HrPersonnelChangeCase.objects.select_for_update().select_related(
            "staff_master_id"
        ).filter(tenant_id=self.tenant_id, id=case_id).first()
        if case is None:
            raise AuthorityReceiptError("CHANGE_NOT_FOUND", "异动案件不存在")
        if int(case.staff_master_id.tenant_id) != self.tenant_id:
            raise AuthorityReceiptError("CROSS_TENANT_REFERENCE", "人员与案件学校不一致")
        return case

    @staticmethod
    def _snapshot(case):
        try:
            return case.effective_snapshot
        except Exception:
            return None

    @staticmethod
    def _next_sequence(case):
        latest = HrChangeAuthorityReceipt.objects.select_for_update().filter(
            change_case=case
        ).order_by("-sequence_no", "-created_at").first()
        return latest.sequence_no + 1 if latest else 1

    @transaction.atomic
    def append_correction(self, correction: HrChangeCorrection) -> HrChangeAuthorityReceipt:
        if correction.tenant_id != self.tenant_id or correction.status != correction.Status.APPLIED:
            raise AuthorityReceiptError("CHANGE_CORRECTION_NOT_APPLIED", "纠错尚未正式应用")
        key = f"correction:{correction.apply_idempotency_key}"
        existing = HrChangeAuthorityReceipt.objects.filter(
            tenant_id=self.tenant_id, idempotency_key=key
        ).first()
        if existing:
            if existing.source_record_id != correction.id:
                raise AuthorityReceiptError("IDEMPOTENCY_KEY_CONFLICT", "回执幂等键冲突")
            return existing
        case = self._case(correction.change_case_id_id)
        from hr_staff.models import HrCorrectionCase

        provider = HrCorrectionCase.objects.filter(
            tenant_id=self.tenant_id,
            id=correction.provider_case_id,
            staff_id=case.staff_master_id_id,
            status="APPLIED",
            version=correction.provider_case_version,
        ).first()
        if provider is None:
            raise AuthorityReceiptError(
                "HR03_CORRECTION_RECEIPT_INVALID",
                "HR03 正式纠错回执不存在或版本不一致",
            )
        return HrChangeAuthorityReceipt.objects.create(
            tenant_id=self.tenant_id,
            change_case=case,
            effective_snapshot=self._snapshot(case),
            sequence_no=self._next_sequence(case),
            kind=HrChangeAuthorityReceipt.Kind.CORRECTION,
            authority_effect=True,
            provider_code="HR03_FORMAL_CORRECTION",
            provider_case_id=provider.id,
            provider_case_version=provider.version,
            provider_snapshot_hash=correction.new_snapshot_hash,
            source_record_id=correction.id,
            idempotency_key=key,
            payload_json={
                "changedFields": correction.applied_fields_json or [],
                "authorityOwner": "HR03",
            },
            effective_at=correction.applied_at or provider.applied_at or timezone.now(),
            sealed_at=timezone.now(),
        )

    @transaction.atomic
    def append_orchestration_rescind(self, rescind: HrChangeRescind) -> HrChangeAuthorityReceipt:
        if rescind.tenant_id != self.tenant_id or rescind.status != rescind.Status.RESCINDED:
            raise AuthorityReceiptError("CHANGE_RESCIND_NOT_APPLIED", "撤销尚未执行")
        key = f"rescind:{rescind.id}"
        existing = HrChangeAuthorityReceipt.objects.filter(
            tenant_id=self.tenant_id, idempotency_key=key
        ).first()
        if existing:
            return existing
        case = self._case(rescind.change_case_id_id)
        return HrChangeAuthorityReceipt.objects.create(
            tenant_id=self.tenant_id,
            change_case=case,
            effective_snapshot=self._snapshot(case),
            sequence_no=self._next_sequence(case),
            kind=HrChangeAuthorityReceipt.Kind.ORCHESTRATION_RESCIND,
            authority_effect=False,
            provider_code="HR06_ORCHESTRATION_ONLY",
            source_record_id=rescind.id,
            idempotency_key=key,
            payload_json={
                "authorityOwner": "HR03",
                "hr03FactsReversed": False,
                "boundary": "HR06 orchestration event rescinded; HR03 facts remain authoritative",
            },
            effective_at=rescind.applied_at or timezone.now(),
            sealed_at=timezone.now(),
        )


def effective_execution_chain(case: HrPersonnelChangeCase) -> dict:
    try:
        snapshot = case.effective_snapshot
    except Exception:
        snapshot = None
    receipts = case.authority_receipts.order_by("sequence_no", "created_at")
    return {
        "authorityOwner": "HR03",
        "executionSnapshot": (
            {
                "id": str(snapshot.id),
                "contentHash": snapshot.content_hash,
                "sealedAt": snapshot.sealed_at.isoformat(),
                "effectiveAt": snapshot.effective_at.isoformat(),
                "targetFactIds": snapshot.target_fact_ids_json,
            }
            if snapshot
            else None
        ),
        "receipts": [
            {
                "id": str(receipt.id),
                "sequenceNo": receipt.sequence_no,
                "kind": receipt.kind,
                "authorityEffect": receipt.authority_effect,
                "providerCode": receipt.provider_code,
                "providerCaseId": str(receipt.provider_case_id) if receipt.provider_case_id else None,
                "contentHash": receipt.content_hash,
                "sealedAt": receipt.sealed_at.isoformat(),
                "payload": receipt.payload_json,
            }
            for receipt in receipts
        ],
    }
