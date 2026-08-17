"""Typed provider gateway for the HR17 SELF experience.

HR17 owns presentation and aggregation only. Source business truth stays in
HR03-HR16. Providers are isolated so one unavailable or failing source cannot
turn into a plausible empty value and cannot take down the whole SELF bootstrap.

Canonical SELF-safe adapters are built in for source domains whose Authority
contracts are already stable on the integration branch. Remaining domains can
still register explicit adapters through ``HR17_SELF_PROVIDER_PATHS``. Missing
or invalid adapters remain UNAVAILABLE; HR17 never falls back to legacy tables,
exposes raw source documents, or copies source state machines.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string

from hr_self.services.identity_service import SelfIdentityContext


class ProviderStatus:
    OK = "OK"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    ERROR = "ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"

    ALL = frozenset({OK, PARTIAL, UNAVAILABLE, STALE, ERROR, NOT_APPLICABLE})


@dataclass(frozen=True)
class SelfProviderResult:
    status: str
    data: Any = None
    source_updated_at: Optional[datetime] = None
    error_code: str = ""
    error_message: str = ""
    provider_version: str = "1.0"
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in ProviderStatus.ALL:
            raise ValueError(f"unsupported provider status: {self.status}")
        if self.status in {ProviderStatus.UNAVAILABLE, ProviderStatus.ERROR} and self.data is not None:
            raise ValueError("unavailable/error provider results must not carry business data")

    @classmethod
    def ok(cls, data, *, source_updated_at=None, provider_version="1.0", meta=None):
        return cls(
            status=ProviderStatus.OK,
            data=data,
            source_updated_at=source_updated_at,
            provider_version=provider_version,
            meta=meta or {},
        )

    @classmethod
    def unavailable(cls, code, message="", *, provider_version="1.0"):
        return cls(
            status=ProviderStatus.UNAVAILABLE,
            data=None,
            error_code=code,
            error_message=message,
            provider_version=provider_version,
        )

    @classmethod
    def error(cls, code, message="", *, provider_version="1.0"):
        return cls(
            status=ProviderStatus.ERROR,
            data=None,
            error_code=code,
            error_message=message,
            provider_version=provider_version,
        )


ProviderCallable = Callable[[SelfIdentityContext], SelfProviderResult]


class SelfProviderRegistry:
    REQUIRED_DOMAINS = tuple(f"HR{number:02d}" for number in range(3, 17))

    def __init__(self):
        self._providers: dict[str, ProviderCallable] = {}

    def register(self, domain: str, provider: ProviderCallable) -> None:
        domain = str(domain or "").strip().upper()
        if domain not in self.REQUIRED_DOMAINS:
            raise ValueError(f"unsupported HR17 source domain: {domain}")
        if not callable(provider):
            raise TypeError("provider must be callable")
        self._providers[domain] = provider

    def registered_domains(self) -> tuple[str, ...]:
        return tuple(domain for domain in self.REQUIRED_DOMAINS if domain in self._providers)

    def call(self, domain: str, context: SelfIdentityContext) -> SelfProviderResult:
        domain = str(domain or "").strip().upper()
        provider = self._providers.get(domain)
        if provider is None:
            return SelfProviderResult.unavailable(
                "SOURCE_PROVIDER_NOT_REGISTERED",
                f"{domain} SELF provider is not registered on this branch",
            )
        try:
            result = provider(context)
        except Exception as exc:
            return SelfProviderResult.error(
                "SOURCE_PROVIDER_ERROR",
                f"{domain} provider failed: {type(exc).__name__}",
            )
        if not isinstance(result, SelfProviderResult):
            return SelfProviderResult.error(
                "SOURCE_PROVIDER_CONTRACT_INVALID",
                f"{domain} provider returned an invalid envelope",
            )
        return result

    def collect(self, context: SelfIdentityContext) -> dict[str, SelfProviderResult]:
        return {domain: self.call(domain, context) for domain in self.REQUIRED_DOMAINS}


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _identifier(value) -> Optional[str]:
    return str(value) if value is not None else None


def _latest_source_updated_at(*groups) -> Optional[datetime]:
    timestamps = [
        getattr(row, "updated_at", None)
        for group in groups
        for row in group
        if getattr(row, "updated_at", None) is not None
    ]
    return max(timestamps, default=None)


def hr03_self_provider(context: SelfIdentityContext) -> SelfProviderResult:
    """Real HR03 SELF adapter using the canonical effective-dated ProfileSelector."""

    from hr_staff.context import build_staff_context
    from hr_staff.selectors.profile import ProfileSelector

    hr03_context = build_staff_context(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        scope_type="SELF",
        scope_staff_ids=[context.staff_id],
        authority_mode="HR03_AUTHORITY",
    )
    data = ProfileSelector(hr03_context).bootstrap(context.staff_id)
    return SelfProviderResult.ok(
        data,
        source_updated_at=hr03_context.request_snapshot_at or timezone.now(),
        provider_version="hr03.profile-bootstrap.1",
        meta={"scope": "SELF", "authority": "HR03_AUTHORITY"},
    )


def hr07_self_provider(context: SelfIdentityContext) -> SelfProviderResult:
    """Read SELF-safe contract metadata from the HR07 Contract Authority.

    Contract document references, version content snapshots and approval internals
    deliberately stay in HR07. HR17 only receives agreement metadata needed by a
    staff member to understand contract status.
    """

    from hr_contracts.models import HrContractAgreement

    agreements = list(
        HrContractAgreement.objects.filter(
            tenant_id=context.tenant_id,
            staff_id=context.staff_id,
        ).order_by("-updated_at")[:20]
    )
    data = {
        "contractAgreements": [
            {
                "id": _identifier(row.id),
                "agreementNo": row.agreement_no,
                "employmentRelationshipId": _identifier(row.employment_relationship_id),
                "title": row.agreement_title,
                "type": row.agreement_type,
                "status": row.status,
                "currentVersionNo": row.current_version_no,
                "updatedAt": _iso(row.updated_at),
            }
            for row in agreements
        ]
    }
    return SelfProviderResult.ok(
        data,
        source_updated_at=_latest_source_updated_at(agreements),
        provider_version="hr07.contract-authority-self.1",
        meta={"scope": "SELF", "authority": "HR07_CONTRACT_AUTHORITY"},
    )


def hr14_self_provider(context: SelfIdentityContext) -> SelfProviderResult:
    """Read appointment progress and facts from the HR14 Appointment Authority.

    Lists are returned instead of guessing one record with ``first()`` because a
    person can legitimately have appointment history and in-flight applications.
    """

    from hr_appointment.models import AppointmentApplicationCase, PositionAppointmentFact

    applications = list(
        AppointmentApplicationCase.objects.filter(
            tenant_id=context.tenant_id,
            person_id=context.person_id,
        ).order_by("-updated_at")[:20]
    )
    facts = list(
        PositionAppointmentFact.objects.filter(
            tenant_id=context.tenant_id,
            person_id=context.person_id,
        ).order_by("-effective_from", "-created_at")[:20]
    )
    data = {
        "appointmentApplications": [
            {
                "id": _identifier(row.id),
                "caseNo": row.case_no,
                "policyVersionId": _identifier(row.policy_version_id),
                "positionInstanceId": row.position_instance_id,
                "batchNo": row.batch_no,
                "requestedLevelCode": row.requested_level_code,
                "status": row.status,
                "updatedAt": _iso(row.updated_at),
            }
            for row in applications
        ],
        "appointmentFacts": [
            {
                "id": _identifier(row.id),
                "appointmentNo": row.appointment_no,
                "positionInstanceId": row.position_instance_id,
                "applicationCaseId": _identifier(row.application_case_id),
                "levelCode": row.level_code,
                "effectiveFrom": _iso(row.effective_from),
                "effectiveTo": _iso(row.effective_to),
                "status": row.status,
                "supersedesFactId": _identifier(row.supersedes_fact_id),
                "createdAt": _iso(row.created_at),
                "updatedAt": _iso(row.updated_at),
            }
            for row in facts
        ],
    }
    return SelfProviderResult.ok(
        data,
        source_updated_at=_latest_source_updated_at(applications, facts),
        provider_version="hr14.appointment-authority-self.1",
        meta={"scope": "SELF", "authority": "HR14_APPOINTMENT_AUTHORITY"},
    )


def hr16_self_provider(context: SelfIdentityContext) -> SelfProviderResult:
    """Read retirement/exit progress and immutable facts from HR16 Authority."""

    from hr_exit.models import ExitCase, ExitFact, RetirementFact

    cases = list(
        ExitCase.objects.filter(
            tenant_id=context.tenant_id,
            person_id=context.person_id,
        ).order_by("-updated_at")[:20]
    )
    exit_facts = list(
        ExitFact.objects.filter(
            tenant_id=context.tenant_id,
            person_id=context.person_id,
        ).order_by("-employment_end_date", "-created_at")[:20]
    )
    retirements = list(
        RetirementFact.objects.filter(
            tenant_id=context.tenant_id,
            person_id=context.person_id,
        ).order_by("-effective_date", "-created_at")[:20]
    )
    data = {
        "exitCases": [
            {
                "id": _identifier(row.id),
                "caseNo": row.case_no,
                "employmentRelationshipId": _identifier(row.employment_relationship_id),
                "exitType": row.exit_type,
                "status": row.status,
                "requestedDate": _iso(row.requested_date),
                "lastWorkingDate": _iso(row.last_working_date),
                "plannedEmploymentEndDate": _iso(row.planned_employment_end_date),
                "plannedAccessEndAt": _iso(row.planned_access_end_at),
                "updatedAt": _iso(row.updated_at),
            }
            for row in cases
        ],
        "exitFacts": [
            {
                "id": _identifier(row.id),
                "factNo": row.fact_no,
                "employmentRelationshipId": _identifier(row.employment_relationship_id),
                "sourceCaseId": _identifier(row.source_case_id),
                "exitType": row.exit_type,
                "employmentEndDate": _iso(row.employment_end_date),
                "lastWorkingDate": _iso(row.last_working_date),
                "accessEndAt": _iso(row.access_end_at),
                "status": row.status,
                "supersedesFactId": _identifier(row.supersedes_fact_id),
                "createdAt": _iso(row.created_at),
                "updatedAt": _iso(row.updated_at),
            }
            for row in exit_facts
        ],
        "retirementFacts": [
            {
                "id": _identifier(row.id),
                "factNo": row.fact_no,
                "exitFactId": _identifier(row.exit_fact_id),
                "retirementType": row.retirement_type,
                "statutoryDate": _iso(row.statutory_date),
                "effectiveDate": _iso(row.effective_date),
                "pensionProcessingStatus": row.pension_processing_status,
                "status": row.status,
                "supersedesFactId": _identifier(row.supersedes_fact_id),
                "createdAt": _iso(row.created_at),
                "updatedAt": _iso(row.updated_at),
            }
            for row in retirements
        ],
    }
    return SelfProviderResult.ok(
        data,
        source_updated_at=_latest_source_updated_at(cases, exit_facts, retirements),
        provider_version="hr16.exit-authority-self.1",
        meta={"scope": "SELF", "authority": "HR16_EXIT_AUTHORITY"},
    )


def configured_self_provider_paths() -> dict[str, str]:
    raw = getattr(settings, "HR17_SELF_PROVIDER_PATHS", {}) or {}
    if not isinstance(raw, Mapping):
        return {}
    configured = {}
    for domain, path in raw.items():
        normalized = str(domain or "").strip().upper()
        if normalized not in SelfProviderRegistry.REQUIRED_DOMAINS:
            continue
        value = str(path or "").strip()
        if value:
            configured[normalized] = value
    return configured


def default_self_provider_registry() -> SelfProviderRegistry:
    from hr_self.services.authority_providers import (
        hr09_self_provider,
        hr10_self_provider,
        hr12_self_provider,
        hr13_self_provider,
        hr15_self_provider,
    )

    registry = SelfProviderRegistry()
    canonical_providers = {
        "HR03": hr03_self_provider,
        "HR07": hr07_self_provider,
        "HR09": hr09_self_provider,
        "HR10": hr10_self_provider,
        "HR12": hr12_self_provider,
        "HR13": hr13_self_provider,
        "HR14": hr14_self_provider,
        "HR15": hr15_self_provider,
        "HR16": hr16_self_provider,
    }
    for domain, provider in canonical_providers.items():
        registry.register(domain, provider)

    for domain, path in configured_self_provider_paths().items():
        # Canonical adapters pin HR17 to the source Authority and cannot be
        # shadowed by runtime configuration or a legacy compatibility provider.
        if domain in canonical_providers:
            continue
        try:
            provider = import_string(path)
        except Exception:
            # Invalid integration configuration must degrade to UNAVAILABLE, not
            # crash HR17 bootstrap or pretend a provider is registered.
            continue
        if callable(provider):
            registry.register(domain, provider)
    return registry
