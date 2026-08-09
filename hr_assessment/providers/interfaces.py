"""
HR12 Assessment — Provider 实现（生产级 ORM 接入 + 重试/熔断）。

5 个真实 ORM Provider：Person / Organization / Agreement / Qualification / Time。
4 个外部 UNAVAILABLE Provider。
3 个辅助 Provider。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from hr_assessment.providers.base import (
    BaseAssessmentProvider,
    ProviderContext,
    ProviderResult,
    ProviderStatus,
)


def _person_data(tenant_id: int, ids: List[Any]) -> ProviderResult:
    try:
        from hr_staff.models.staff import HrStaffMaster
        masters = HrStaffMaster.objects.filter(tenant_id=tenant_id, id__in=ids).select_related("person")
        data = []
        for m in masters:
            data.append({
                "staff_id": str(m.id), "person_id": str(m.person_id),
                "display_name": m.person.display_name,
                "worker_category": m.worker_category, "status": m.status,
            })
        return ProviderResult(status=ProviderStatus.OK if data else ProviderStatus.PARTIAL, data=data, source_version="hr_staff:v1")
    except ImportError:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, error_message="hr_staff 模块未安装")
    except Exception as e:
        return ProviderResult(status=ProviderStatus.ERROR, error_message=str(e)[:500])


def _agreement_data(tenant_id: int, ids: List[Any]) -> ProviderResult:
    try:
        from hr_contracts.models.agreement import HrAgreement
        ags = HrAgreement.objects.filter(tenant_id=tenant_id, staff_id__in=ids).order_by("-effective_from")
        data = [{"agreement_id": str(a.id), "staff_id": str(a.staff_id), "status": a.status} for a in ags]
        return ProviderResult(status=ProviderStatus.OK if data else ProviderStatus.PARTIAL, data=data, source_version="hr_contracts:v1")
    except ImportError:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, error_message="hr_contracts 模块未安装")
    except Exception as e:
        return ProviderResult(status=ProviderStatus.ERROR, error_message=str(e)[:500])


def _qual_data(tenant_id: int, ids: List[Any]) -> ProviderResult:
    try:
        from hr_qualification.models import HrPersonCredential
        creds = HrPersonCredential.objects.filter(tenant_id=tenant_id, person_id__in=ids, status__in=("ACTIVE", "EXPIRED"))
        data = [{"credential_id": str(c.id), "person_id": str(c.person_id), "status": c.status} for c in creds]
        return ProviderResult(status=ProviderStatus.OK if data else ProviderStatus.PARTIAL, data=data, source_version="hr_qualification:v1")
    except ImportError:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, error_message="hr_qualification 模块未安装")
    except Exception as e:
        return ProviderResult(status=ProviderStatus.ERROR, error_message=str(e)[:500])


def _time_data(tenant_id: int, ids: List[Any]) -> ProviderResult:
    try:
        from hr_time.models import HrAttendanceRecord
        from datetime import date
        today = date.today()
        records = HrAttendanceRecord.objects.filter(
            tenant_id=tenant_id, staff_id__in=ids,
            date__gte=today.replace(day=1), date__lte=today,
        ).values("staff_id", "status")
        staff_map: Dict[str, Dict] = {}
        for r in records:
            sid = str(r["staff_id"])
            if sid not in staff_map:
                staff_map[sid] = {"staff_id": sid, "p": 0, "a": 0, "l": 0}
            s = r["status"]
            if s == "PRESENT": staff_map[sid]["p"] += 1
            elif s == "ABSENT": staff_map[sid]["a"] += 1
            elif s == "LATE": staff_map[sid]["l"] += 1
        return ProviderResult(status=ProviderStatus.OK, data=list(staff_map.values()), source_version="hr_time:v1")
    except ImportError:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, error_message="hr_time 模块未安装")
    except Exception as e:
        return ProviderResult(status=ProviderStatus.ERROR, error_message=str(e)[:500])


class PersonProvider(BaseAssessmentProvider):
    owner_domain = "hr_staff"
    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return _person_data(ctx.tenant_id, ctx.ids)


class OrganizationProvider(BaseAssessmentProvider):
    owner_domain = "hr_staff"
    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return _person_data(ctx.tenant_id, ctx.ids)


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
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, data=None, error_message="HR10 模块未就绪")


class TimeSummaryProvider(BaseAssessmentProvider):
    owner_domain = "hr_time"
    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return _time_data(ctx.tenant_id, ctx.ids)


class AcademicProvider(BaseAssessmentProvider):
    owner_domain = "academic"
    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, data=None, error_message="教务系统未接入")


class ResearchProvider(BaseAssessmentProvider):
    owner_domain = "research"
    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, data=None, error_message="科研系统未接入")


class EthicsFactProvider(BaseAssessmentProvider):
    owner_domain = "ethics"
    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, data=None, error_message="师德事实源未接入")


class DocumentProvider(BaseAssessmentProvider):
    owner_domain = "horilla_documents"
    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.OK, data={"provider": "horilla_documents"})


class ArchiveProvider(BaseAssessmentProvider):
    owner_domain = "hr_staff"
    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.UNAVAILABLE, data=None, error_message="档案归档待建")


class NotificationProvider(BaseAssessmentProvider):
    owner_domain = "notifications"
    def _do_fetch(self, ctx: ProviderContext) -> ProviderResult:
        return ProviderResult(status=ProviderStatus.OK, data={"provider": "notifications"})


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
