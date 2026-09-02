"""Idempotent HR15 intake for verified external-workforce settlement bases."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction

from hr_payroll.models import ExternalSettlementBasisInput


_PERIOD = re.compile(r"^(20\d{2})-(0[1-9]|1[0-2])$")


class ExternalSettlementInputError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ExternalSettlementInputOutcome:
    value: ExternalSettlementBasisInput
    created: bool


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ExternalSettlementInputService:
    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise ExternalSettlementInputError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)

    def receive(
        self,
        *,
        engagement_id,
        period,
        source_version,
        verified_workload,
        eligible_items,
        policy_ref="",
        idempotency_key,
    ) -> ExternalSettlementInputOutcome:
        try:
            engagement_uuid = uuid.UUID(str(engagement_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ExternalSettlementInputError(
                "EXTERNAL_SETTLEMENT_ENGAGEMENT_INVALID", "engagement_id is invalid"
            ) from exc
        period = str(period or "").strip()
        if not _PERIOD.fullmatch(period):
            raise ExternalSettlementInputError(
                "EXTERNAL_SETTLEMENT_PERIOD_INVALID", "period must use YYYY-MM"
            )
        if isinstance(source_version, bool) or not isinstance(source_version, int) or source_version < 1:
            raise ExternalSettlementInputError(
                "EXTERNAL_SETTLEMENT_VERSION_INVALID", "source_version is invalid"
            )
        try:
            workload = Decimal(str(verified_workload)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ExternalSettlementInputError(
                "EXTERNAL_SETTLEMENT_WORKLOAD_INVALID", "verified_workload is invalid"
            ) from exc
        if workload < 0:
            raise ExternalSettlementInputError(
                "EXTERNAL_SETTLEMENT_WORKLOAD_INVALID", "verified_workload cannot be negative"
            )
        if not isinstance(eligible_items, list):
            raise ExternalSettlementInputError(
                "EXTERNAL_SETTLEMENT_ITEMS_INVALID", "eligible_items must be a list"
            )
        policy_ref = str(policy_ref or "").strip()
        if len(policy_ref) > 64:
            raise ExternalSettlementInputError(
                "EXTERNAL_SETTLEMENT_POLICY_INVALID", "policy_ref is too long"
            )
        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key or len(idempotency_key) > 128:
            raise ExternalSettlementInputError(
                "EXTERNAL_SETTLEMENT_IDEMPOTENCY_INVALID", "idempotency_key is invalid"
            )
        payload = {
            "sourceDomain": "HR08",
            "engagementId": str(engagement_uuid),
            "period": period,
            "sourceVersion": source_version,
            "verifiedWorkload": str(workload),
            "eligibleItems": eligible_items,
            "policyRef": policy_ref,
        }
        content_hash = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()

        with transaction.atomic():
            existing = ExternalSettlementBasisInput.objects.filter(
                tenant_id=self.tenant_id, idempotency_key=idempotency_key
            ).first()
            if existing:
                if existing.content_hash != content_hash:
                    raise ExternalSettlementInputError(
                        "EXTERNAL_SETTLEMENT_IDEMPOTENCY_CONFLICT",
                        "idempotency_key already identifies different settlement input",
                    )
                return ExternalSettlementInputOutcome(existing, False)
            try:
                with transaction.atomic():
                    value = ExternalSettlementBasisInput.objects.create(
                        tenant_id=self.tenant_id,
                        source_domain="HR08",
                        source_engagement_id=engagement_uuid,
                        source_version=source_version,
                        period_code=period,
                        verified_workload=workload,
                        eligible_items_json=eligible_items,
                        policy_ref=policy_ref,
                        content_hash=content_hash,
                        idempotency_key=idempotency_key,
                    )
            except IntegrityError as exc:
                concurrent = ExternalSettlementBasisInput.objects.filter(
                    tenant_id=self.tenant_id, idempotency_key=idempotency_key
                ).first()
                if concurrent and concurrent.content_hash == content_hash:
                    return ExternalSettlementInputOutcome(concurrent, False)
                raise ExternalSettlementInputError(
                    "EXTERNAL_SETTLEMENT_VERSION_CONFLICT",
                    "settlement input version already exists with different content",
                ) from exc
        return ExternalSettlementInputOutcome(value, True)
