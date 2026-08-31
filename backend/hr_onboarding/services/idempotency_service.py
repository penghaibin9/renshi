"""Database-backed idempotency state machine for HR05 write commands."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from hr_onboarding.api.exceptions import (
    Hr05ApiError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    TenantContextRequiredError,
)
from hr_onboarding.models import HrOnboardingIdempotencyRecord, IdempotencyStatus


DEFAULT_LEASE_SECONDS = 120


def canonical_request_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class IdempotencyClaim:
    record: HrOnboardingIdempotencyRecord
    execute: bool

    @property
    def is_replay(self) -> bool:
        return not self.execute


class DurableIdempotencyService:
    """Claim and finish commands under a tenant/operation/key identity.

    Callers must invoke ``claim`` in the same outer database transaction as
    the business write.  The unique constraint serializes first creation;
    ``select_for_update`` serializes retries and lease recovery.
    """

    def __init__(self, *, tenant_id: int, operation: str):
        if not tenant_id:
            raise TenantContextRequiredError()
        operation = (operation or "").strip()
        if not operation or len(operation) > 64:
            raise Hr05ApiError("非法幂等操作标识")
        self.tenant_id = int(tenant_id)
        self.operation = operation

    @staticmethod
    def _normalize_key(value: str) -> str:
        key = (value or "").strip()
        if not key:
            raise Hr05ApiError("缺少 Idempotency-Key（写操作必须幂等）")
        if len(key) > 128:
            raise Hr05ApiError("Idempotency-Key 超过 128 字符")
        return key

    def claim(
        self,
        *,
        idempotency_key: str,
        request_payload: Any,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> IdempotencyClaim:
        key = self._normalize_key(idempotency_key)
        request_hash = canonical_request_hash(request_payload)
        now = timezone.now()
        lease_owner = uuid.uuid4().hex
        lookup = {
            "tenant_id": self.tenant_id,
            "operation": self.operation,
            "idempotency_key": key,
        }

        record = (
            HrOnboardingIdempotencyRecord.objects.select_for_update()
            .filter(**lookup)
            .first()
        )
        created = record is None
        if created:
            try:
                # Savepoint keeps an expected concurrent unique race from
                # poisoning the caller's surrounding atomic transaction.
                with transaction.atomic():
                    record = HrOnboardingIdempotencyRecord.objects.create(
                        **lookup,
                        request_hash=request_hash,
                        status=IdempotencyStatus.IN_PROGRESS,
                        lease_owner=lease_owner,
                        lease_expires_at=now + timedelta(seconds=lease_seconds),
                        last_attempt_at=now,
                    )
            except IntegrityError:
                created = False
                record = HrOnboardingIdempotencyRecord.objects.select_for_update().get(
                    **lookup
                )

        if record.request_hash != request_hash:
            raise IdempotencyConflictError(
                "相同 Idempotency-Key 已用于不同请求",
                details={"operation": self.operation},
            )
        if created:
            return IdempotencyClaim(record=record, execute=True)
        if record.status in (
            IdempotencyStatus.SUCCEEDED,
            IdempotencyStatus.FAILED_TERMINAL,
        ):
            return IdempotencyClaim(record=record, execute=False)
        if (
            record.status == IdempotencyStatus.IN_PROGRESS
            and record.lease_expires_at
            and record.lease_expires_at > now
        ):
            raise IdempotencyInProgressError("相同请求正在处理中，请稍后重试")

        # Retryable failure or a worker whose lease expired after a crash.
        record.status = IdempotencyStatus.IN_PROGRESS
        record.attempt_count += 1
        record.lease_owner = lease_owner
        record.lease_expires_at = now + timedelta(seconds=lease_seconds)
        record.last_attempt_at = now
        record.completed_at = None
        record.error_code = ""
        record.save(
            update_fields=[
                "status",
                "attempt_count",
                "lease_owner",
                "lease_expires_at",
                "last_attempt_at",
                "completed_at",
                "error_code",
                "updated_at",
            ]
        )
        return IdempotencyClaim(record=record, execute=True)

    @staticmethod
    def succeed(
        record: HrOnboardingIdempotencyRecord,
        *,
        authority_type: str,
        authority_id: Any,
        response_summary: dict | None = None,
    ) -> None:
        record.status = IdempotencyStatus.SUCCEEDED
        record.authority_type = authority_type[:64]
        record.authority_id = str(authority_id)[:64]
        record.response_summary = response_summary or {}
        record.error_code = ""
        record.lease_owner = ""
        record.lease_expires_at = None
        record.completed_at = timezone.now()
        record.save(
            update_fields=[
                "status",
                "authority_type",
                "authority_id",
                "response_summary",
                "error_code",
                "lease_owner",
                "lease_expires_at",
                "completed_at",
                "updated_at",
            ]
        )

    @staticmethod
    def fail(
        record: HrOnboardingIdempotencyRecord,
        *,
        error_code: str,
        retryable: bool,
        response_summary: dict | None = None,
        authority_type: str = "",
        authority_id: Any = "",
    ) -> None:
        record.status = (
            IdempotencyStatus.FAILED_RETRYABLE
            if retryable
            else IdempotencyStatus.FAILED_TERMINAL
        )
        record.error_code = (error_code or "HR05_API_ERROR")[:64]
        record.response_summary = response_summary or {}
        record.authority_type = authority_type[:64]
        record.authority_id = str(authority_id)[:64]
        record.lease_owner = ""
        record.lease_expires_at = None
        record.completed_at = timezone.now()
        record.save(
            update_fields=[
                "status",
                "error_code",
                "response_summary",
                "authority_type",
                "authority_id",
                "lease_owner",
                "lease_expires_at",
                "completed_at",
                "updated_at",
            ]
        )
