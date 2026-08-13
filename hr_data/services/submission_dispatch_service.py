"""Durable asynchronous dispatch authority for HR18 formal submissions.

The configured provider must enqueue work and return a durable ``dispatchRef``.
The request thread never marks the snapshot SUBMITTED. It only records
DISPATCH_QUEUED; the async worker later calls ``confirm_dispatched`` or
``record_dispatch_failure`` on SubmissionLifecycleService with the same ref.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from hr_data.models import SubmissionSnapshot


class SubmissionDispatchError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class SubmissionDispatchResult:
    snapshot: SubmissionSnapshot
    queued: bool
    dispatch_ref: str


class SubmissionDispatchService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise SubmissionDispatchError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock(self, submission_id) -> SubmissionSnapshot:
        snapshot = (
            SubmissionSnapshot.objects.select_for_update()
            .filter(id=submission_id, tenant_id=self.tenant_id)
            .first()
        )
        if snapshot is None:
            raise SubmissionDispatchError("SUBMISSION_NOT_FOUND", "submission snapshot not found")
        return snapshot

    @staticmethod
    def _provider_path() -> str:
        return str(getattr(settings, "HR18_SUBMISSION_DISPATCH_PROVIDER", "") or "").strip()

    @transaction.atomic
    def queue(self, submission_id) -> SubmissionDispatchResult:
        snapshot = self._lock(submission_id)
        if snapshot.status == SubmissionSnapshot.Status.DISPATCH_QUEUED:
            if not snapshot.dispatch_ref:
                raise SubmissionDispatchError(
                    "SUBMISSION_DISPATCH_STATE_CORRUPT",
                    "queued submission is missing dispatch_ref",
                )
            return SubmissionDispatchResult(snapshot, False, snapshot.dispatch_ref)
        if snapshot.status not in {
            SubmissionSnapshot.Status.APPROVED,
            SubmissionSnapshot.Status.DISPATCH_FAILED,
        }:
            raise SubmissionDispatchError(
                "SUBMISSION_INVALID_STATE",
                f"submission status {snapshot.status} cannot be queued for dispatch",
            )

        provider_path = self._provider_path()
        if not provider_path:
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_UNAVAILABLE",
                "no formal asynchronous HR18 submission dispatch provider is registered",
            )
        try:
            provider = import_string(provider_path)
        except Exception as exc:
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_UNAVAILABLE",
                f"submission dispatch provider cannot be loaded: {type(exc).__name__}",
            ) from exc

        idempotency_key = (
            f"hr18:{self.tenant_id}:{snapshot.id}:{snapshot.payload_hash.lower()}"
        )
        try:
            receipt = provider(
                tenant_id=self.tenant_id,
                submission=snapshot,
                idempotency_key=idempotency_key,
                actor_user_id=self.actor_user_id,
            )
        except Exception as exc:
            snapshot.status = SubmissionSnapshot.Status.DISPATCH_FAILED
            snapshot.dispatch_error = str(exc)[:2000]
            snapshot.updated_by = self.actor_user_id
            snapshot.save(
                update_fields=[
                    "status",
                    "dispatch_error",
                    "updated_by",
                    "updated_at",
                ]
            )
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_FAILED",
                snapshot.dispatch_error or "submission dispatch provider failed",
            ) from exc

        if not isinstance(receipt, Mapping) or receipt.get("queued") is not True:
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_CONTRACT_INVALID",
                "dispatch provider must return a mapping with queued=true",
            )
        dispatch_ref = str(receipt.get("dispatchRef") or "").strip()
        if not dispatch_ref:
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_CONTRACT_INVALID",
                "dispatch provider must return a durable dispatchRef",
            )
        if len(dispatch_ref) > 255:
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_REF_INVALID", "dispatchRef exceeds 255 characters"
            )

        snapshot.status = SubmissionSnapshot.Status.DISPATCH_QUEUED
        snapshot.dispatch_ref = dispatch_ref
        snapshot.dispatch_requested_at = timezone.now()
        snapshot.dispatch_error = ""
        snapshot.updated_by = self.actor_user_id
        snapshot.save(
            update_fields=[
                "status",
                "dispatch_ref",
                "dispatch_requested_at",
                "dispatch_error",
                "updated_by",
                "updated_at",
            ]
        )
        return SubmissionDispatchResult(snapshot, True, dispatch_ref)
