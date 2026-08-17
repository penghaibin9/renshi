"""
HR12 Assessment — Provider 实现（生产级 ORM 接入 + 重试/熔断）。

5 个真实 ORM Provider：Person / Organization / Agreement / Qualification / Time。
4 个外部 UNAVAILABLE Provider。
3 个辅助 Provider。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from hr_assessment.providers.base import (
    BaseAssessmentProvider,
    ProviderContext,
    ProviderResult,
    ProviderStatus,
)


def _empty_result(source_version: str) -> ProviderResult:
    """空 ID 集合是一次完整成功的查询，不应触发下游依赖或被误报 UNAVAILABLE。"""
    return ProviderResult(
        status=ProviderStatus.OK,
        data=[],
        source_version=source_version,
    )


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
                    # Provider contract keeps the neutral worker_category key;
                    # HR03 authority currently names the field staff_category_code.
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
            status=ProviderStatus.OK if len(seen) == len(set(ids)) else ProviderStatus.PARTIAL,
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


def _time_data(tenant_id: int, ids: List[Any]) -> ProviderResult:
    if not ids:
        return _empty_result("hr_time:v1")
    try:
        from datetime import date

        from hr_time.models import HrAttendanceRecord

        today = date.today()
        records = HrAttendanceRecord.objects.filter(
            tenant_id=tenant_id,
            staff_id__in=ids,
            date__gte=today.replace(day=1),
            date__lte=today,
        ).values("staff_id", "status")
        staff_map: Dict[str, Dict] = {}
        for record in records:
            staff_id = str(record["staff_id"])
            if staff_id not in staff_map:
                staff_map[staff_id] = {
                    "staff_id": staff_id,
                    "p": 0,
                    "a": 0,
                    "l": 0,
                }
            status = record["status"]
            if status == "PRESENT":
                staff_map[staff_id]["p"] += 1
            elif status == "ABSENT":
                staff_map[staff_id]["a"] += 1
            elif status == "LATE":
                staff_map[staff_id]["l"] += 1
        return ProviderResult(
            status=ProviderStatus.OK,
            data=list(staff_map.values()),
            source_version="hr_time:v1",
        )
    except ImportError:
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            error_message="hr_time 模块未安装",
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
        return ProviderResult(
            status=ProviderStatus.UNAVAILABLE,
            data=None,
            error_message="HR10 模块未就绪",
        )


class TimeSummaryProvider(BaseAssessmentProvider):
    owner_domain = "hr_time"

    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return _time_data(ctx.tenant_id, ctx.ids)


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
            status=ProviderStatus.OK,
            data={"provider": "horilla_documents"},
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
            status=ProviderStatus.OK,
            data={"provider": "notifications"},
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
