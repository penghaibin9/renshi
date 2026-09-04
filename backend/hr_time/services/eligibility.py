"""
hr_time/services/eligibility.py

S2 Eligibility Resolver（总册 §41、§25）。

resolve_time_policy(tenant, staff, assignment, as_of) 是唯一解析入口：
- 输出 policyVersionId / recordingMethod / matchedRules / resolutionReason；
- 多条同优先级冲突 → TIME_POLICY_AMBIGUOUS（fail-closed）；
- 无覆盖 → TIME_POLICY_NOT_FOUND（fail-closed）；
- HR03 Person/Assignment Provider 不可用 → TIME_SOURCE_UNAVAILABLE（显式失败，禁止静默 fallback）。

优先级冻结（从高到低）：
1. explicit person exception
2. assignment scope（岗位/任职）
3. org scope（组织）
4. worker category / employment type scope
5. tenant default
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from django.db import models

from hr_time.enums import PolicyStatus
from hr_time.models.policy import HrTimePolicyVersion
from hr_time.providers.base import HrProviderError, PersonProvider
from hr_time.providers.hr03 import LocalHr03PersonProvider


class EligibilityError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class TimePolicyResolution:
    """解析结果（总册 §41）。"""

    policy_version_id: Optional[int]
    policy_pack_id: Optional[int]
    recording_method: Optional[str]
    calendar_version_id: Optional[int] = None
    schedule_source: Optional[str] = None
    matched_rules: list = field(default_factory=list)
    resolution_reason: str = ""
    status: str = "OK"  # OK / AMBIGUOUS / NOT_FOUND / SOURCE_UNAVAILABLE
    error_code: Optional[str] = None


class TimePolicyResolver:
    """Eligibility Resolver（§41）。"""

    # 适用范围匹配优先级（高→低）
    SCOPE_PRIORITY = (
        "PERSON_EXCEPTION",
        "ASSIGNMENT",
        "ORG",
        "WORKER_CATEGORY",
        "EMPLOYMENT_TYPE",
        "TENANT_DEFAULT",
    )

    def __init__(self, person_provider: Optional[PersonProvider] = None):
        self.person_provider = person_provider

    @staticmethod
    def _value(snapshot, key):
        if snapshot is None:
            return None
        if isinstance(snapshot, dict):
            return snapshot.get(key)
        return getattr(snapshot, key, None)

    @staticmethod
    def _contains(values, candidate) -> bool:
        return bool(values) and str(candidate) in {str(value) for value in values}

    def _match_scope(self, version: HrTimePolicyVersion, *, person, assignment) -> Optional[str]:
        """
        判断版本是否适用于该人员，返回命中范围；不适用返回 None。
        版本适用范围存于 policy_pack.effective_scope（JSON）。
        S2 基础实现：
        - scope 为空 → 视为 TENANT_DEFAULT；
        - PERSON_EXCEPTION 需要 person 信息（缺 provider → None 交由调用方判 SOURCE_UNAVAILABLE）。
        """
        scope = version.policy_pack.effective_scope or {}
        if not scope:
            return "TENANT_DEFAULT"

        if scope.get("type") == "PERSON_EXCEPTION":
            if person is None:
                return None
            if self._contains(
                scope.get("person_ids") or scope.get("personIds"),
                self._value(person, "staff_master_id"),
            ):
                return "PERSON_EXCEPTION"
            return None

        if scope.get("type") == "ASSIGNMENT":
            if assignment is None:
                return None
            if self._contains(
                scope.get("assignment_ids") or scope.get("assignmentIds"),
                self._value(assignment, "assignment_id"),
            ):
                return "ASSIGNMENT"
            return None

        if scope.get("type") == "ORG":
            if assignment is None:
                return None
            if self._contains(
                scope.get("org_ids") or scope.get("orgIds"),
                self._value(assignment, "org_id"),
            ):
                return "ORG"
            return None

        if scope.get("type") == "WORKER_CATEGORY":
            if person is None:
                return None
            if self._contains(
                scope.get("categories"), self._value(person, "worker_category")
            ):
                return "WORKER_CATEGORY"
            return None

        if scope.get("type") == "EMPLOYMENT_TYPE":
            if person is None:
                return None
            if self._contains(
                scope.get("employment_types") or scope.get("employmentTypes"),
                self._value(person, "employment_type"),
            ):
                return "EMPLOYMENT_TYPE"
            return None

        if scope.get("type") == "TENANT_DEFAULT":
            return "TENANT_DEFAULT"

        # 其他类型（ORG/ASSIGNMENT）S2 先不匹配，返回 None（S3 排班/组织模型后实现）
        return None

    def resolve(
        self,
        *,
        tenant_id: int,
        staff_master_id: int,
        assignment_id: Optional[int] = None,
        as_of: date,
    ) -> TimePolicyResolution:
        versions = (
            HrTimePolicyVersion.objects.filter(
                tenant_id=tenant_id,
                status=PolicyStatus.PUBLISHED,
                effective_from__lte=as_of,
                policy_pack__status="ACTIVE",
            )
            .filter(
                models.Q(effective_to__isnull=True) | models.Q(effective_to__gt=as_of)
            )
            .select_related("policy_pack", "recording_profile")
            .order_by("-effective_from", "-version_no")
        )
        if not versions.exists():
            return TimePolicyResolution(
                policy_version_id=None,
                policy_pack_id=None,
                recording_method=None,
                status="NOT_FOUND",
                error_code="TIME_POLICY_NOT_FOUND",
                resolution_reason="无已发布且生效的政策版本",
            )

        # person/assignment 信息：HR03 Provider（缺则 SOURCE_UNAVAILABLE）
        person = None
        assignment = None
        scoped_types = {
            str(version.policy_pack.effective_scope.get("type", "TENANT_DEFAULT"))
            for version in versions
        }
        needs_hr03 = bool(scoped_types - {"", "TENANT_DEFAULT"})
        provider = self.person_provider or (
            LocalHr03PersonProvider(tenant_id) if needs_hr03 else None
        )
        if provider is not None:
            try:
                person = provider.get_person(
                    legacy_employee_id=staff_master_id, as_of=as_of
                )
                if assignment_id:
                    assignment = provider.get_assignment(
                        assignment_id=assignment_id, as_of=as_of
                    )
                    if str(self._value(assignment, "staff_master_id")) != str(
                        self._value(person, "staff_master_id")
                    ):
                        raise HrProviderError(
                            "CROSS_TENANT_REFERENCE",
                            "任职不属于当前教职工",
                        )
            except HrProviderError as exc:
                return TimePolicyResolution(
                    policy_version_id=None,
                    policy_pack_id=None,
                    recording_method=None,
                    status="SOURCE_UNAVAILABLE",
                    error_code=exc.code,
                    resolution_reason=f"HR03 人员 Provider 不可用: {exc.message}",
                )

        matched = []
        for version in versions:
            scope = self._match_scope(
                version, person=person, assignment=assignment
            )
            if scope is not None:
                matched.append((self.SCOPE_PRIORITY.index(scope), version, scope))

        if not matched:
            return TimePolicyResolution(
                policy_version_id=None,
                policy_pack_id=None,
                recording_method=None,
                status="NOT_FOUND",
                error_code="TIME_POLICY_NOT_FOUND",
                resolution_reason="已发布版本均不适用于该人员",
            )

        matched.sort(key=lambda item: item[0])
        top_priority = matched[0][0]
        top_versions = [item for item in matched if item[0] == top_priority]

        if len(top_versions) > 1:
            return TimePolicyResolution(
                policy_version_id=None,
                policy_pack_id=None,
                recording_method=None,
                status="AMBIGUOUS",
                error_code="TIME_POLICY_AMBIGUOUS",
                matched_rules=[v.id for _, v, _ in top_versions],
                resolution_reason=f"同一优先级 {top_versions[0][2]} 命中多个版本，需人工裁决",
            )

        _, version, scope = top_versions[0]
        return TimePolicyResolution(
            policy_version_id=version.id,
            policy_pack_id=version.policy_pack_id,
            recording_method=(
                version.recording_profile.method if version.recording_profile else None
            ),
            matched_rules=[{"version_id": version.id, "scope": scope}],
            resolution_reason=f"命中范围: {scope}",
            status="OK",
        )
