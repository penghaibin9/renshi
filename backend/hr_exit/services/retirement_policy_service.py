"""Versioned retirement policy management and authoritative HR03 precheck."""

from __future__ import annotations

import calendar
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from django.db import transaction
from django.db.models import Max, Q

from horilla.hr_event_service import emit_registered_event
from hr_exit.archive_registry import (
    EVENT_RETIREMENT_POLICY_ACTIVATED,
    EVENT_RETIREMENT_PRECHECK_COMPLETED,
)
from hr_exit.models import RetirementPolicy, RetirementPrecheck
from hr_staff.models import HrEmploymentRelationship


class RetirementPolicyError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class RetirementPrecheckResult:
    precheck: RetirementPrecheck
    created: bool


def _months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def _add_months(value: date, months: int) -> date:
    absolute = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(absolute, 12)
    month = month_zero + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class RetirementPolicyService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise RetirementPolicyError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @staticmethod
    def _bounded(value, *, field: str, maximum: int, required: bool = False) -> str:
        result = str(value or "").strip().upper()
        if required and not result:
            raise RetirementPolicyError(
                f"RETIREMENT_POLICY_{field.upper()}_REQUIRED",
                f"{field} is required",
            )
        if len(result) > maximum:
            raise RetirementPolicyError(
                f"RETIREMENT_POLICY_{field.upper()}_INVALID",
                f"{field} exceeds {maximum} characters",
            )
        return result

    @transaction.atomic
    def create_draft(
        self,
        *,
        policy_code: str,
        retirement_type: str,
        retirement_age_months: int,
        effective_from: date,
        rationale: str,
        gender_code: str = "ANY",
        minimum_service_months: int = 0,
        effective_to: date | None = None,
        staff_category_code: str = "",
        relationship_type: str = "",
        special_condition_code: str = "",
        priority: int = 0,
    ) -> RetirementPolicy:
        code = self._bounded(policy_code, field="policy_code", maximum=64, required=True)
        retirement_type = self._bounded(
            retirement_type, field="retirement_type", maximum=32, required=True
        )
        gender_code = self._bounded(gender_code, field="gender_code", maximum=3) or "ANY"
        if gender_code not in RetirementPolicy.Gender.values:
            raise RetirementPolicyError(
                "RETIREMENT_POLICY_GENDER_INVALID", "gender_code must be ANY/M/F/O/U"
            )
        rationale = str(rationale or "").strip()
        if not rationale or len(rationale) > 2000:
            raise RetirementPolicyError(
                "RETIREMENT_POLICY_RATIONALE_INVALID",
                "rationale is required and limited to 2000 characters",
            )
        if not isinstance(effective_from, date):
            raise RetirementPolicyError(
                "RETIREMENT_POLICY_EFFECTIVE_FROM_REQUIRED", "effective_from is required"
            )
        if effective_to is not None and effective_to <= effective_from:
            raise RetirementPolicyError(
                "RETIREMENT_POLICY_DATE_RANGE_INVALID",
                "effective_to must be after effective_from",
            )
        try:
            age_months = int(retirement_age_months)
            service_months = int(minimum_service_months)
            priority = int(priority)
        except (TypeError, ValueError) as exc:
            raise RetirementPolicyError(
                "RETIREMENT_POLICY_NUMBER_INVALID", "age/service/priority must be integers"
            ) from exc
        if not 1 <= age_months <= 1200 or not 0 <= service_months <= 1200:
            raise RetirementPolicyError(
                "RETIREMENT_POLICY_NUMBER_INVALID",
                "age must be 1..1200 months and service must be 0..1200 months",
            )

        latest_version = (
            RetirementPolicy.objects.filter(tenant_id=self.tenant_id, policy_code=code)
            .aggregate(value=Max("version_no"))["value"]
            or 0
        )
        previous = (
            RetirementPolicy.objects.filter(
                tenant_id=self.tenant_id,
                policy_code=code,
                status=RetirementPolicy.Status.ACTIVE,
            )
            .order_by("-version_no")
            .first()
        )
        content = {
            "policyCode": code,
            "version": latest_version + 1,
            "retirementType": retirement_type,
            "genderCode": gender_code,
            "staffCategoryCode": self._bounded(
                staff_category_code, field="staff_category_code", maximum=32
            ),
            "relationshipType": self._bounded(
                relationship_type, field="relationship_type", maximum=32
            ),
            "specialConditionCode": self._bounded(
                special_condition_code, field="special_condition_code", maximum=64
            ),
            "retirementAgeMonths": age_months,
            "minimumServiceMonths": service_months,
            "effectiveFrom": effective_from.isoformat(),
            "effectiveTo": effective_to.isoformat() if effective_to else None,
            "priority": priority,
            "rationale": rationale,
        }
        content_hash = hashlib.sha256(
            json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return RetirementPolicy.objects.create(
            tenant_id=self.tenant_id,
            policy_code=code,
            version_no=latest_version + 1,
            status=RetirementPolicy.Status.DRAFT,
            content_hash=content_hash,
            retirement_type=retirement_type,
            gender_code=gender_code,
            staff_category_code=content["staffCategoryCode"],
            relationship_type=content["relationshipType"],
            special_condition_code=content["specialConditionCode"],
            retirement_age_months=age_months,
            minimum_service_months=service_months,
            effective_from=effective_from,
            effective_to=effective_to,
            priority=priority,
            rationale=rationale,
            supersedes_policy_id=previous.id if previous else None,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def activate(self, policy_id) -> RetirementPolicy:
        policy = (
            RetirementPolicy.objects.select_for_update()
            .filter(id=policy_id, tenant_id=self.tenant_id)
            .first()
        )
        if policy is None:
            raise RetirementPolicyError(
                "RETIREMENT_POLICY_NOT_FOUND", "retirement policy not found inside tenant"
            )
        if policy.status == RetirementPolicy.Status.ACTIVE:
            return policy
        if policy.status != RetirementPolicy.Status.DRAFT:
            raise RetirementPolicyError(
                "RETIREMENT_POLICY_INVALID_STATE", "only DRAFT policy can be activated"
            )
        previous = list(
            RetirementPolicy.objects.select_for_update().filter(
                tenant_id=self.tenant_id,
                policy_code=policy.policy_code,
                status=RetirementPolicy.Status.ACTIVE,
            )
        )
        for item in previous:
            item.status = RetirementPolicy.Status.RETIRED
            item.updated_by = self.actor_user_id
            item.save(update_fields=["status", "updated_by", "updated_at"])
        policy.status = RetirementPolicy.Status.ACTIVE
        policy.updated_by = self.actor_user_id
        policy.save(update_fields=["status", "updated_by", "updated_at"])
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_RETIREMENT_POLICY_ACTIVATED,
            payload={
                "policyId": str(policy.id),
                "policyCode": policy.policy_code,
                "version": policy.version_no,
                "contentHash": policy.content_hash,
            },
        )
        return policy


class RetirementPrecheckService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise RetirementPolicyError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @transaction.atomic
    def evaluate(
        self,
        *,
        person_id,
        employment_relationship_id,
        as_of: date,
        idempotency_key: str,
        special_condition_codes: Iterable[str] = (),
    ) -> RetirementPrecheckResult:
        key = str(idempotency_key or "").strip()
        if not key or len(key) > 128:
            raise RetirementPolicyError(
                "RETIREMENT_PRECHECK_IDEMPOTENCY_KEY_INVALID",
                "idempotency_key is required and limited to 128 characters",
            )
        if not isinstance(as_of, date):
            raise RetirementPolicyError(
                "RETIREMENT_PRECHECK_AS_OF_REQUIRED", "as_of is required"
            )
        conditions = tuple(
            sorted({str(value or "").strip().upper() for value in special_condition_codes if str(value or "").strip()})
        )
        existing = (
            RetirementPrecheck.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, idempotency_key=key)
            .first()
        )
        if existing is not None:
            original_conditions = tuple(existing.input_snapshot_json.get("specialConditionCodes", ()))
            if (
                str(existing.person_id) != str(person_id)
                or str(existing.employment_relationship_id) != str(employment_relationship_id)
                or existing.as_of != as_of
                or original_conditions != conditions
            ):
                raise RetirementPolicyError(
                    "RETIREMENT_PRECHECK_IDEMPOTENCY_CONFLICT",
                    "idempotency key belongs to a different frozen precheck request",
                )
            return RetirementPrecheckResult(existing, False)

        relationship = (
            HrEmploymentRelationship.objects.select_related("staff_id__person_id")
            .filter(
                id=employment_relationship_id,
                tenant_id=self.tenant_id,
                staff_id__person_id_id=person_id,
            )
            .first()
        )
        if relationship is None:
            raise RetirementPolicyError(
                "RETIREMENT_PRECHECK_SOURCE_NOT_FOUND",
                "HR03 employment relationship/person was not found inside tenant",
            )
        person = relationship.staff_id.person_id
        staff = relationship.staff_id
        service_months = _months_between(relationship.effective_from, as_of)
        policies = RetirementPolicy.objects.filter(
            tenant_id=self.tenant_id,
            status=RetirementPolicy.Status.ACTIVE,
            effective_from__lte=as_of,
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
        policies = policies.filter(
            Q(gender_code=RetirementPolicy.Gender.ANY)
            | Q(gender_code=person.gender_code or RetirementPolicy.Gender.UNSPECIFIED)
        ).filter(Q(staff_category_code="") | Q(staff_category_code=staff.staff_category_code))
        policies = policies.filter(
            Q(relationship_type="") | Q(relationship_type=relationship.relationship_type)
        ).order_by("-priority", "-effective_from", "-version_no")
        matched = next(
            (
                policy
                for policy in policies
                if not policy.special_condition_code
                or policy.special_condition_code in conditions
            ),
            None,
        )

        statutory_date = None
        reason_codes = []
        if person.birth_date is None:
            decision = RetirementPrecheck.Decision.MANUAL_REVIEW
            reason_codes.append("HR03_BIRTH_DATE_UNAVAILABLE")
        elif matched is None:
            decision = RetirementPrecheck.Decision.MANUAL_REVIEW
            reason_codes.append("NO_ACTIVE_POLICY_MATCH")
        else:
            statutory_date = _add_months(person.birth_date, matched.retirement_age_months)
            if as_of < statutory_date:
                reason_codes.append("STATUTORY_DATE_NOT_REACHED")
            if service_months < matched.minimum_service_months:
                reason_codes.append("MINIMUM_SERVICE_NOT_REACHED")
            decision = (
                RetirementPrecheck.Decision.ELIGIBLE
                if not reason_codes
                else RetirementPrecheck.Decision.NOT_YET
            )

        input_snapshot = {
            "sourceAuthority": "HR03",
            "sourcePersonId": str(person.id),
            "sourceEmploymentRelationshipId": str(relationship.id),
            "sourceStaffVersion": staff.version,
            "sourceEmploymentVersion": relationship.version,
            "genderCode": person.gender_code or "U",
            "staffCategoryCode": staff.staff_category_code,
            "relationshipType": relationship.relationship_type,
            "serviceMonths": service_months,
            "specialConditionCodes": list(conditions),
            "birthDatePresent": person.birth_date is not None,
        }
        explanation = {
            "reasonCodes": reason_codes,
            "rationale": matched.rationale if matched else "需要人工核验或配置政策",
            "requiredRetirementAgeMonths": matched.retirement_age_months if matched else None,
            "requiredMinimumServiceMonths": matched.minimum_service_months if matched else None,
            "observedServiceMonths": service_months,
            "policyContentHash": matched.content_hash if matched else "",
        }
        precheck = RetirementPrecheck.objects.create(
            tenant_id=self.tenant_id,
            idempotency_key=key,
            person_id=person.id,
            employment_relationship_id=relationship.id,
            as_of=as_of,
            decision=decision,
            retirement_type=matched.retirement_type if matched else "",
            statutory_date=statutory_date,
            matched_policy_id=matched.id if matched else None,
            matched_policy_version=matched.version_no if matched else None,
            input_snapshot_json=input_snapshot,
            explanation_json=explanation,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_RETIREMENT_PRECHECK_COMPLETED,
            payload={
                "precheckId": str(precheck.id),
                "personId": str(precheck.person_id),
                "employmentRelationshipId": str(precheck.employment_relationship_id),
                "decision": precheck.decision,
                "matchedPolicyId": str(precheck.matched_policy_id) if precheck.matched_policy_id else None,
                "matchedPolicyVersion": precheck.matched_policy_version,
                "asOf": precheck.as_of.isoformat(),
            },
        )
        return RetirementPrecheckResult(precheck, True)
