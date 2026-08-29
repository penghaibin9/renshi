"""HR12 assessment provider implementations.

Internal HR domains are read through their source-owned public contracts where
formal evidence exists. External systems that are not actually configured stay
explicitly UNAVAILABLE; there is no silent legacy or zero-value fallback.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from django.utils import timezone

from hr_assessment.providers.base import (
    BaseAssessmentProvider,
    ProviderContext,
    ProviderResult,
    ProviderStatus,
)


def _empty_result(source_version: str) -> ProviderResult:
    """An empty requested ID set is a complete query, not UNAVAILABLE."""
    return ProviderResult(status=ProviderStatus.OK, data=[], source_version=source_version)


def _ctx_as_of_date(ctx: ProviderContext) -> date:
    value = ctx.as_of
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            return timezone.localtime(value).date()
        return value.date()
    if isinstance(value, date):
        return value
    raise ValueError("provider as_of must be a date or datetime")


def _person_data(ctx: ProviderContext) -> ProviderResult:
    if not ctx.ids:
        return _empty_result("hr03-staff-evidence-v1")
    try:
        from hr_staff.public import (
            PROVIDER_VERSION,
            StaffEvidenceUnavailable,
            get_staff_evidence,
        )

        evidence = get_staff_evidence(
            tenant_id=ctx.tenant_id,
            staff_ids=ctx.ids,
            as_of=_ctx_as_of_date(ctx),
            source_version=ctx.source_version,
        )
    except StaffEvidenceUnavailable as exc:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            data=None,
            error_message=f"{exc.code}: {exc}",
            source_version="hr03-staff-evidence-v1",
        )

    blockers = tuple(evidence.missing_staff_ids) + tuple(
        evidence.uncertain_identity_staff_ids
    )
    status = ProviderStatus.PARTIAL if blockers else ProviderStatus.OK
    errors = []
    if evidence.missing_staff_ids:
        errors.append(
            "STAFF_BASIS_UNAVAILABLE: missing tenant/as-of HR03 staff: "
            + ",".join(str(value) for value in evidence.missing_staff_ids)
        )
    if evidence.uncertain_identity_staff_ids:
        errors.append(
            "STAFF_IDENTITY_HISTORY_UNAVAILABLE: current identity fields changed after as_of for staff: "
            + ",".join(str(value) for value in evidence.uncertain_identity_staff_ids)
        )
    return ProviderResult(
        status=status,
        data=[row.snapshot() for row in evidence.rows],
        error_message="; ".join(errors),
        source_version=PROVIDER_VERSION,
    )


def _organization_data(ctx: ProviderContext) -> ProviderResult:
    if not ctx.ids:
        return _empty_result("hr02-organization-evidence-v1")
    try:
        from hr_structure.public import (
            PROVIDER_VERSION,
            OrganizationEvidenceUnavailable,
            get_organization_evidence,
        )

        evidence = get_organization_evidence(
            tenant_id=ctx.tenant_id,
            organization_ids=ctx.ids,
            as_of=_ctx_as_of_date(ctx),
            source_version=ctx.source_version,
        )
    except OrganizationEvidenceUnavailable as exc:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            data=None,
            error_message=f"{exc.code}: {exc}",
            source_version="hr02-organization-evidence-v1",
        )

    status = ProviderStatus.PARTIAL if evidence.missing_organization_ids else ProviderStatus.OK
    error = ""
    if evidence.missing_organization_ids:
        error = (
            "ORGANIZATION_BASIS_UNAVAILABLE: missing tenant/as-of HR02 organizations: "
            + ",".join(str(value) for value in evidence.missing_organization_ids)
        )
    return ProviderResult(
        status=status,
        data=[row.snapshot() for row in evidence.rows],
        error_message=error,
        source_version=PROVIDER_VERSION,
    )


def _agreement_data(ctx: ProviderContext) -> ProviderResult:
    if not ctx.ids:
        return _empty_result("hr07-agreement-evidence-v1")
    try:
        from hr_contracts.public import (
            PROVIDER_VERSION,
            AgreementEvidenceUnavailable,
            get_formal_agreement_evidence,
        )

        evidence = get_formal_agreement_evidence(
            tenant_id=ctx.tenant_id,
            staff_ids=ctx.ids,
            as_of=_ctx_as_of_date(ctx),
            source_version=ctx.source_version,
        )
    except AgreementEvidenceUnavailable as exc:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            data=None,
            error_message=f"{exc.code}: {exc}",
            source_version="hr07-agreement-evidence-v1",
        )

    status = ProviderStatus.PARTIAL if evidence.missing_staff_ids else ProviderStatus.OK
    error = ""
    if evidence.missing_staff_ids:
        error = (
            "AGREEMENT_BASIS_UNAVAILABLE: missing tenant/as-of HR07 agreements for staff: "
            + ",".join(str(value) for value in evidence.missing_staff_ids)
        )
    return ProviderResult(
        status=status,
        data=[row.snapshot() for row in evidence.rows],
        error_message=error,
        source_version=PROVIDER_VERSION,
    )


def _qual_data(ctx: ProviderContext) -> ProviderResult:
    if not ctx.ids:
        return _empty_result("hr09-credential-evidence-v1")
    try:
        from hr_qualification.public import (
            PROVIDER_VERSION,
            CredentialEvidenceUnavailable,
            get_formal_credential_evidence,
        )

        evidence = get_formal_credential_evidence(
            tenant_id=ctx.tenant_id,
            staff_ids=ctx.ids,
            as_of=_ctx_as_of_date(ctx),
            source_version=ctx.source_version,
        )
    except CredentialEvidenceUnavailable as exc:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            data=None,
            error_message=f"{exc.code}: {exc}",
            source_version="hr09-credential-evidence-v1",
        )

    status = ProviderStatus.PARTIAL if evidence.uncertain_staff_ids else ProviderStatus.OK
    error = ""
    if evidence.uncertain_staff_ids:
        error = (
            "CREDENTIAL_HISTORY_UNAVAILABLE: historical HR09 state cannot be proven for staff: "
            + ",".join(str(value) for value in evidence.uncertain_staff_ids)
        )
    return ProviderResult(
        status=status,
        data=[row.snapshot() for row in evidence.rows],
        error_message=error,
        source_version=PROVIDER_VERSION,
        source_updated_at=max(
            (row.last_verified_at for row in evidence.rows if row.last_verified_at is not None),
            default=None,
        ),
    )


class PersonProvider(BaseAssessmentProvider):
    owner_domain = "hr_staff"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return _person_data(ctx)


class OrganizationProvider(BaseAssessmentProvider):
    owner_domain = "hr_structure"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return _organization_data(ctx)


class AgreementProvider(BaseAssessmentProvider):
    owner_domain = "hr_contracts"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return _agreement_data(ctx)


class QualificationProvider(BaseAssessmentProvider):
    owner_domain = "hr_qualification"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return _qual_data(ctx)


class DevelopmentProvider(BaseAssessmentProvider):
    owner_domain = "hr_development"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        if not ctx.ids:
            return _empty_result("hr10-development-fact-v1")
        try:
            from hr10_development.public import (
                PROVIDER_VERSION,
                DevelopmentEvidenceUnavailable,
                get_verified_development_facts,
            )

            evidence = get_verified_development_facts(
                tenant_id=ctx.tenant_id,
                staff_ids=ctx.ids,
                as_of=_ctx_as_of_date(ctx),
                source_version=ctx.source_version,
            )
        except DevelopmentEvidenceUnavailable as exc:
            return ProviderResult(
                status=ProviderStatus.UNAVAILABLE,
                data=None,
                error_message=f"{exc.code}: {exc}",
                source_version="hr10-development-fact-v1",
            )
        data = [fact.snapshot() for fact in evidence.facts]
        status = ProviderStatus.PARTIAL if evidence.missing_staff_ids else ProviderStatus.OK
        error = ""
        if evidence.missing_staff_ids:
            error = (
                "SOURCE_IDENTITY_MAPPING_UNAVAILABLE: missing canonical HR03 staff mappings: "
                + ",".join(str(value) for value in evidence.missing_staff_ids)
            )
        return ProviderResult(
            status=status,
            data=data,
            error_message=error,
            source_version=PROVIDER_VERSION,
            source_updated_at=max(
                (fact.updated_at for fact in evidence.facts if fact.updated_at is not None),
                default=None,
            ),
        )


class TimeSummaryProvider(BaseAssessmentProvider):
    owner_domain = "hr_time"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        if not ctx.ids:
            return _empty_result("hr11-time-close-v1")
        try:
            from hr_time.public import (
                PROVIDER_VERSION,
                TimeCloseEvidenceUnavailable,
                get_closed_time_summary_evidence,
            )

            evidence = get_closed_time_summary_evidence(
                tenant_id=ctx.tenant_id,
                staff_ids=ctx.ids,
                as_of=_ctx_as_of_date(ctx),
                source_version=ctx.source_version,
            )
        except TimeCloseEvidenceUnavailable as exc:
            return ProviderResult(
                status=ProviderStatus.UNAVAILABLE,
                data=None,
                error_message=f"{exc.code}: {exc}",
                source_version="hr11-time-close-v1",
            )
        data = [
            {**row.snapshot(), "timeClose": evidence.period.snapshot()}
            for row in evidence.staff_rows
        ]
        status = ProviderStatus.PARTIAL if evidence.missing_staff_ids else ProviderStatus.OK
        error = ""
        if evidence.missing_staff_ids:
            error = (
                "TIME_BASIS_UNAVAILABLE: missing HR11 basis or canonical identity mapping: "
                + ",".join(str(value) for value in evidence.missing_staff_ids)
            )
        return ProviderResult(
            status=status,
            data=data,
            error_message=error,
            source_version=PROVIDER_VERSION,
            source_updated_at=evidence.period.closed_at,
        )


class AcademicProvider(BaseAssessmentProvider):
    owner_domain = "academic"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            data=None,
            error_message="教务系统未接入",
        )


class ResearchProvider(BaseAssessmentProvider):
    owner_domain = "research"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            data=None,
            error_message="科研系统未接入",
        )


class EthicsFactProvider(BaseAssessmentProvider):
    owner_domain = "ethics"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            data=None,
            error_message="师德事实源未接入",
        )


class DocumentProvider(BaseAssessmentProvider):
    owner_domain = "horilla_documents"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            data=None,
            error_message="文档服务未配置真实事实查询/回执接口",
            source_version="horilla_documents:unconfigured",
        )


class ArchiveProvider(BaseAssessmentProvider):
    owner_domain = "hr_staff"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            data=None,
            error_message="档案归档待建",
        )


class NotificationProvider(BaseAssessmentProvider):
    owner_domain = "notifications"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            data=None,
            error_message="通知服务未配置真实投递/回执接口",
            source_version="notifications:unconfigured",
        )


PROVIDER_REGISTRY = {
    "person": PersonProvider(),
    "organization": OrganizationProvider(),
    "agreement": AgreementProvider(),
    "qualification": QualificationProvider(),
    "development": DevelopmentProvider(),
    "time_summary": TimeSummaryProvider(),
    "academic": AcademicProvider(),
    "research": ResearchProvider(),
    "ethics_fact": EthicsFactProvider(),
    "document": DocumentProvider(),
    "archive": ArchiveProvider(),
    "notification": NotificationProvider(),
}


def get_provider(name: str) -> Optional[BaseAssessmentProvider]:
    return PROVIDER_REGISTRY.get(name)
