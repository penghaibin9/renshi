"""Canonical, tenant-scoped HR07 contract expiry worker.

The old implementation referenced migration-era ``HrAgreement`` classes that
do not exist in canonical HR07. This worker reads the sealed agreement/version
chain and creates a renewal or human-review case. It never decides that an
employment relationship is legally terminated.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Optional

from django.db import transaction

from horilla.hr_event_service import emit_registered_event
from hr_contracts.events import EVENT_EXPIRY_ACTION_CREATED
from hr_contracts.models import (
    HrContractAgreement,
    HrContractCase,
    HrContractExpiryPolicy,
    HrContractExpiryRiskFact,
    HrContractVersion,
)
from hr_contracts.services.agreement_service import AgreementService
from hr_contracts.services.lifecycle_service import ContractLifecycleService


class ContractExpiryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class CanonicalContractExpiryService:
    """Evaluate one tenant at an explicit business date and create actions."""

    _SCANNABLE_STATUSES = (
        HrContractAgreement.Status.ACTIVE,
        HrContractAgreement.Status.EXPIRING,
        HrContractAgreement.Status.RENEWAL_IN_PROGRESS,
        HrContractAgreement.Status.EXPIRED,
    )

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise ContractExpiryError(
                "TENANT_CONTEXT_REQUIRED", "one concrete tenant_id is required"
            )
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @staticmethod
    def _canonical_hash(payload: dict) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _current_version(self, agreement: HrContractAgreement) -> HrContractVersion:
        if not agreement.current_version_no:
            raise ContractExpiryError(
                "CONTRACT_FORMAL_VERSION_REQUIRED",
                "agreement has no current formal version",
            )
        version = (
            HrContractVersion.objects.filter(
                tenant_id=self.tenant_id,
                agreement_id=agreement.id,
                version_no=agreement.current_version_no,
            )
            .order_by("id")
            .first()
        )
        if version is None:
            raise ContractExpiryError(
                "CONTRACT_VERSION_NOT_FOUND", "current contract version is missing"
            )
        if (
            version.status != HrContractVersion.Status.EFFECTIVE
            or version.signed_at is None
            or not version.signed_document_ref.strip()
            or not isinstance(version.content_snapshot_json, dict)
            or not version.content_snapshot_json
            or version.content_hash
            != AgreementService._content_hash(version.content_snapshot_json)
        ):
            raise ContractExpiryError(
                "CONTRACT_VERSION_EVIDENCE_INVALID",
                "current version is not a complete, verified EFFECTIVE fact",
            )
        return version

    def _policy_for(self, agreement: HrContractAgreement) -> HrContractExpiryPolicy:
        exact = list(
            HrContractExpiryPolicy.objects.filter(
                tenant_id=self.tenant_id,
                agreement_type=agreement.agreement_type,
                active=True,
            ).order_by("policy_version")[:2]
        )
        candidates = exact
        if not candidates:
            candidates = list(
                HrContractExpiryPolicy.objects.filter(
                    tenant_id=self.tenant_id,
                    agreement_type="",
                    active=True,
                ).order_by("policy_version")[:2]
            )
        if not candidates:
            raise ContractExpiryError(
                "EXPIRY_POLICY_REQUIRED",
                "no active expiry policy matches this agreement type",
            )
        if len(candidates) != 1:
            raise ContractExpiryError(
                "EXPIRY_POLICY_AMBIGUOUS",
                "more than one active expiry policy matches this agreement type",
            )
        policy = candidates[0]
        if (
            not policy.policy_version.strip()
            or policy.action_type
            not in HrContractExpiryPolicy.ActionType.values
            or policy.content_hash != policy.expected_content_hash()
        ):
            raise ContractExpiryError(
                "EXPIRY_POLICY_EVIDENCE_INVALID",
                "expiry policy content hash does not match its authority payload",
            )
        return policy

    @staticmethod
    def _decision(version, policy, as_of: date) -> Optional[dict]:
        if version.effective_to is None:
            return None
        days_to_expiry = (version.effective_to - as_of).days
        if days_to_expiry > policy.warning_days:
            return None
        overdue_days = max(0, -days_to_expiry)
        overdue = days_to_expiry < 0
        return {
            "stage": (
                HrContractExpiryRiskFact.Stage.OVERDUE
                if overdue
                else HrContractExpiryRiskFact.Stage.EXPIRING
            ),
            "severity": (
                HrContractExpiryRiskFact.Severity.CRITICAL
                if overdue and overdue_days >= policy.critical_after_days
                else (
                    HrContractExpiryRiskFact.Severity.HIGH
                    if overdue
                    else HrContractExpiryRiskFact.Severity.MEDIUM
                )
            ),
            "daysToExpiry": days_to_expiry,
            "dueDate": version.effective_to,
        }

    @staticmethod
    def _key(agreement, version, action_type: str) -> str:
        raw = f"{agreement.tenant_id}:{agreement.id}:{version.id}:{action_type}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _blocked(agreement, error: ContractExpiryError) -> dict:
        return {
            "agreementId": str(agreement.id),
            "agreementNo": agreement.agreement_no,
            "code": error.code,
            "message": str(error),
        }

    def scan(
        self, *, as_of: date, dry_run: bool = False, limit: int = 500
    ) -> dict:
        if type(as_of) is not date:
            raise ContractExpiryError(
                "EXPIRY_AS_OF_REQUIRED", "an explicit as_of business date is required"
            )
        if limit <= 0 or limit > 5000:
            raise ContractExpiryError(
                "EXPIRY_LIMIT_INVALID", "limit must be between 1 and 5000"
            )
        agreement_ids = list(
            HrContractAgreement.objects.filter(
                tenant_id=self.tenant_id,
                status__in=self._SCANNABLE_STATUSES,
            )
            .order_by("agreement_no", "id")
            .values_list("id", flat=True)[:limit]
        )
        result = {
            "tenantId": self.tenant_id,
            "asOf": as_of.isoformat(),
            "dryRun": bool(dry_run),
            "scanned": len(agreement_ids),
            "eligible": 0,
            "createdCases": 0,
            "createdRisks": 0,
            "replayed": 0,
            "blocked": 0,
            "blockers": [],
            "actions": [],
        }
        for agreement_id in agreement_ids:
            agreement = HrContractAgreement.objects.get(
                id=agreement_id, tenant_id=self.tenant_id
            )
            try:
                version = self._current_version(agreement)
                policy = self._policy_for(agreement)
                decision = self._decision(version, policy, as_of)
            except ContractExpiryError as error:
                result["blocked"] += 1
                result["blockers"].append(self._blocked(agreement, error))
                continue
            if decision is None:
                continue
            result["eligible"] += 1
            if dry_run:
                result["actions"].append(
                    self._action_summary(agreement, version, policy, decision, False)
                )
                continue
            action = self._execute_one(agreement_id=agreement.id, as_of=as_of)
            if action["replayed"]:
                result["replayed"] += 1
            else:
                result["createdCases"] += 1
                result["createdRisks"] += 1
            result["actions"].append(action)
        return result

    @staticmethod
    def _action_summary(agreement, version, policy, decision, replayed):
        return {
            "agreementId": str(agreement.id),
            "agreementNo": agreement.agreement_no,
            "versionId": str(version.id),
            "dueDate": decision["dueDate"].isoformat(),
            "stage": decision["stage"],
            "severity": decision["severity"],
            "decision": policy.action_type,
            "policyVersion": policy.policy_version,
            "policyHash": policy.content_hash,
            "replayed": replayed,
        }

    @transaction.atomic
    def _execute_one(self, *, agreement_id, as_of: date) -> dict:
        agreement = (
            HrContractAgreement.objects.select_for_update()
            .filter(id=agreement_id, tenant_id=self.tenant_id)
            .first()
        )
        if agreement is None:
            raise ContractExpiryError(
                "CONTRACT_NOT_FOUND", "agreement left the tenant during scan"
            )
        version = self._current_version(agreement)
        policy = self._policy_for(agreement)
        decision = self._decision(version, policy, as_of)
        if decision is None:
            raise ContractExpiryError(
                "EXPIRY_ACTION_NO_LONGER_ELIGIBLE",
                "agreement is no longer eligible after acquiring the lock",
            )
        idempotency_key = self._key(agreement, version, policy.action_type)
        existing = HrContractExpiryRiskFact.objects.filter(
            tenant_id=self.tenant_id, idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            return {
                **self._action_summary(agreement, version, policy, decision, True),
                "caseId": str(existing.action_case_id),
                "riskFactId": str(existing.id),
            }

        case_type = (
            HrContractCase.CaseType.RENEW
            if policy.action_type
            == HrContractExpiryPolicy.ActionType.CREATE_RENEWAL_CASE
            else HrContractCase.CaseType.REVIEW
        )
        case_no = f"EXP-{idempotency_key[:24].upper()}"
        lifecycle = ContractLifecycleService(
            self.tenant_id, actor_user_id=self.actor_user_id
        )
        case = lifecycle.create_case(
            case_no=case_no,
            agreement_id=agreement.id,
            case_type=case_type,
            requested_effective_from=version.effective_to,
            reason_code=(
                "CONTRACT_OVERDUE"
                if decision["stage"] == HrContractExpiryRiskFact.Stage.OVERDUE
                else "CONTRACT_EXPIRING"
            ),
            reason_text=(
                "Canonical HR07 expiry policy created this case for human action; "
                "it does not terminate the contract or employment relationship."
            ),
        )
        case = lifecycle.submit_case(case_id=case.id)

        if case_type == HrContractCase.CaseType.REVIEW:
            target_status = (
                HrContractAgreement.Status.EXPIRED
                if decision["stage"] == HrContractExpiryRiskFact.Stage.OVERDUE
                else HrContractAgreement.Status.EXPIRING
            )
            if agreement.status != target_status:
                agreement.status = target_status
                agreement.updated_by = self.actor_user_id
                agreement.save(update_fields=["status", "updated_by", "updated_at"])

        evidence = {
            "agreementId": str(agreement.id),
            "agreementNo": agreement.agreement_no,
            "contractVersionId": str(version.id),
            "contractVersionNo": version.version_no,
            "contractContentHash": version.content_hash,
            "dueDate": version.effective_to.isoformat(),
            "observedAsOf": as_of.isoformat(),
            "daysToExpiry": decision["daysToExpiry"],
            "riskStage": decision["stage"],
            "severity": decision["severity"],
            "decision": policy.action_type,
            "policyVersion": policy.policy_version,
            "policyHash": policy.content_hash,
            "caseId": str(case.id),
            "caseNo": case.case_no,
        }
        fact = HrContractExpiryRiskFact.objects.create(
            tenant_id=self.tenant_id,
            agreement=agreement,
            contract_version=version,
            action_case=case,
            risk_stage=decision["stage"],
            severity=decision["severity"],
            due_date=version.effective_to,
            observed_as_of=as_of,
            days_to_expiry=decision["daysToExpiry"],
            policy_version=policy.policy_version,
            policy_hash=policy.content_hash,
            evidence_json=evidence,
            evidence_hash=self._canonical_hash(evidence),
            idempotency_key=idempotency_key,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_EXPIRY_ACTION_CREATED,
            payload={
                **evidence,
                "expiryRiskFactId": str(fact.id),
                "idempotencyKey": idempotency_key,
            },
            correlation_id=idempotency_key[:32],
        )
        return {
            **self._action_summary(agreement, version, policy, decision, False),
            "caseId": str(case.id),
            "riskFactId": str(fact.id),
        }
