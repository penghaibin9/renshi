"""HR12 assessment provider implementations.

Internal HR domains are read through their source-owned public contracts where
formal evidence exists. External systems that are not actually configured stay
explicitly UNAVAILABLE; there is no silent legacy or zero-value fallback.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from hr_assessment.providers.base import (
    BaseAssessmentProvider,
    ProviderContext,
    ProviderResult,
    ProviderStatus,
)


def _empty_result(source_version: str) -> ProviderResult:
    """An empty requested ID set is a complete query, not UNAVAILABLE."""
    return ProviderResult(
        status=ProviderStatus.OK,
        data=[],
        source_version=source_version,
    )


def _ctx_as_of_date(ctx: ProviderContext) -> date:
    value = ctx.as_of
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ValueError("provider as_of must be a date or datetime")


def _person_data(tenant_id: int, ids: List[Any]) -> ProviderResult:
    if not ids:
        return _empty_result("hr_staff:v1")
    try:
        from hr_staff.models.staff import HrStaffMaster

        masters = HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            id__in=ids,
        ).select_related("person_id")
        data = []
        for master in masters:
            person = master.person_id
            data.append(
                {
                    "staff_id": str(master.id),
                    "person_id": str(master.person_id_id),
                    "display_name": person.preferred_name or person.legal_name,
                    "worker_category": master.staff_category_code,
                    "status": master.current_employment_status or person.status,
                }
            )
        return ProviderResult(
            status=ProviderStatus.OK if data else ProviderStatus.PARTIAL,
            data=data,
            source_version="hr_staff:v1",
        )
    except ImportError:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            error_message="hr_staff 模块未安装",
        )
    except Exception as exc:
        return ProviderResult(
            status=ProviderStatus.ERROR,
            error_message=str(exc)[:500],
        )


def _organization_data(tenant_id: int, ids: List[Any]) -> ProviderResult:
    if not ids:
        return _empty_result("hr_structure:v1")
    try:
        from hr_structure.models.organization import HrOrganizationVersion

        versions = (
            HrOrganizationVersion.objects.filter(
                tenant_id=tenant_id,
                organization_id_id__in=ids,
                status="EFFECTIVE",
            )
            .select_related("organization_id")
            .order_by("organization_id_id", "-validity_from", "-version_no")
        )
        data = []
        seen = set()
        for version in versions:
            organization_pk = version.organization_id_id
            if organization_pk in seen:
                continue
            seen.add(organization_pk)
            organization = version.organization_id
            data.append(
                {
                    "organization_id": str(organization_pk),
                    "stable_code": organization.stable_code,
                    "name": version.name,
                    "short_name": version.short_name,
                    "org_type": version.org_type,
                    "identity_status": organization.identity_status,
                }
            )
        return ProviderResult(
            status=(
                ProviderStatus.OK if len(seen) == len(set(ids)) else ProviderStatus.PARTIAL
            ),
            data=data,
            source_version="hr_structure:v1",
        )
    except ImportError:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            error_message="hr_structure 模块未安装",
        )
    except Exception as exc:
        return ProviderResult(
            status=ProviderStatus.ERROR,
            error_message=str(exc)[:500],
        )


def _agreement_data(tenant_id: int, ids: List[Any]) -> ProviderResult:
    if not ids:
        return _empty_result("hr_contracts:v1")
    try:
        from hr_contracts.models.agreement import HrAgreement

        agreements = HrAgreement.objects.filter(
            tenant_id=tenant_id,
            staff_id__in=ids,
        ).order_by("-effective_from")
        data = [
            {
                "agreement_id": str(agreement.id),
                "staff_id": str(agreement.staff_id),
                "status": agreement.status,
            }
            for agreement in agreements
        ]
        return ProviderResult(
            status=ProviderStatus.OK if data else ProviderStatus.PARTIAL,
            data=data,
            source_version="hr_contracts:v1",
        )
    except ImportError:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            error_message="hr_contracts 模块未安装",
        )
    except Exception as exc:
        return ProviderResult(
            status=ProviderStatus.ERROR,
            error_message=str(exc)[:500],
        )


def _qual_data(tenant_id: int, ids: List[Any]) -> ProviderResult:
    if not ids:
        return _empty_result("hr_qualification:v1")
    try:
        from hr_qualification.models import HrPersonCredential

        credentials = HrPersonCredential.objects.filter(
            tenant_id=tenant_id,
            person_id__in=ids,
            status__in=("ACTIVE", "EXPIRED"),
        )
        data = [
            {
                "credential_id": str(credential.id),
                "person_id": str(credential.person_id),
                "status": credential.status,
            }
            for credential in credentials
        ]
        return ProviderResult(
            status=ProviderStatus.OK if data else ProviderStatus.PARTIAL,
            data=data,
            source_version="hr_qualification:v1",
        )
    except ImportError:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            error_message="hr_qualification 模块未安装",
        )
    except Exception as exc:
        return ProviderResult(
            status=ProviderStatus.ERROR,
            error_message=str(exc)[:500],
        )


class PersonProvider(BaseAssessmentProvider):
    owner_domain = "hr_staff"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return _person_data(ctx.tenant_id, ctx.ids)


class OrganizationProvider(BaseAssessmentProvider):
    owner_domain = "hr_structure"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return _organization_data(ctx.tenant_id, ctx.ids)


class AgreementProvider(BaseAssessmentProvider):
    owner_domain = "hr_contracts"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return _agreement_data(ctx.tenant_id, ctx.ids)


class QualificationProvider(BaseAssessmentProvider):
    owner_domain = "hr_qualification"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return _qual_data(ctx.tenant_id, ctx.ids)


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
            {
                **row.snapshot(),
                "timeClose": evidence.period.snapshot(),
            }
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
