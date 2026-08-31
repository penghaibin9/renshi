"""Project source-owned facts into HR17 unified todos and progress rows.

This remains an Experience Authority: source status is never rewritten and
unavailable providers do not become empty business collections.
"""

from __future__ import annotations

from collections.abc import Mapping

from hr_self.services.provider_gateway import ProviderStatus


_READABLE = {
    ProviderStatus.OK,
    ProviderStatus.PARTIAL,
    ProviderStatus.STALE,
    ProviderStatus.NOT_APPLICABLE,
}
_TASK_TERMINAL = {"COMPLETED", "CANCELLED", "CANCELED", "WAIVED", "SKIPPED"}

_PROGRESS_COLLECTIONS = {
    "HR04": (
        ("applications", "招聘申请", ("applicationNo", "id")),
        ("offers", "录用通知", ("offerNo", "id")),
    ),
    "HR05": (
        ("onboardingCases", "入职办理", ("caseNo", "id")),
        ("probationCases", "试用期", ("caseNo", "id")),
    ),
    "HR06": (("changeCases", "人事异动", ("caseNo", "id")),),
    "HR07": (("contractAgreements", "合同协议", ("title", "agreementNo", "id")),),
    "HR08": (("externalEngagements", "校外人员业务", ("engagementNo", "id")),),
    "HR09": (("credentials", "资质证书", ("credentialName", "credentialNo", "id")),),
    "HR10": (("developmentFacts", "培养发展", ("title", "factNo", "id")),),
    "HR11": (("timesheets", "工时填报", ("periodCode", "id")),),
    "HR12": (("assessmentCases", "考核办理", ("caseNo", "id")),),
    "HR13": (("titleApplications", "职称申报", ("applicationNo", "id")),),
    "HR14": (("appointmentApplications", "岗位聘任", ("applicationNo", "id")),),
    "HR15": (("payrollResults", "工资结果", ("periodCode", "resultNo", "id")),),
    "HR16": (("exitCases", "离退办理", ("caseNo", "id")),),
}


def _first(row: Mapping, fields, fallback="—"):
    for field in fields:
        value = row.get(field)
        if value not in {None, ""}:
            return str(value)
    return fallback


def _source_routes(services) -> dict[str, str]:
    routes = {}
    for item in services or ():
        if not isinstance(item, Mapping):
            continue
        domain = str(item.get("source_domain", "") or "").upper()
        route = str(item.get("route", "") or "")
        if domain and route.startswith("/") and not route.startswith("//"):
            routes.setdefault(domain, route)
    return routes


class SelfExperienceProjectionService:
    def __init__(self, *, provider_results: Mapping, services=()):
        self.provider_results = provider_results
        self.routes = _source_routes(services)

    def todos(self) -> list[dict]:
        result = self.provider_results.get("HR05")
        if result is None or result.status not in _READABLE or not isinstance(result.data, Mapping):
            return []
        rows = result.data.get("tasks", ())
        if not isinstance(rows, list):
            return []
        items = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            status = str(row.get("status", "") or "").upper()
            if status in _TASK_TERMINAL:
                continue
            item_id = str(row.get("id", "") or "").strip()
            if not item_id:
                continue
            items.append(
                {
                    "key": f"HR05:task:{item_id}",
                    "sourceDomain": "HR05",
                    "sourceType": "onboarding_task",
                    "sourceId": item_id,
                    "title": str(row.get("title", "") or row.get("code", "") or "入职待办"),
                    "status": status or "PENDING",
                    "dueAt": row.get("dueAt"),
                    "updatedAt": row.get("updatedAt"),
                    "actionRoute": self.routes.get("HR05"),
                }
            )
        return sorted(items, key=lambda item: (item.get("dueAt") or "9999", item["key"]))

    def progress(self) -> list[dict]:
        items = []
        for domain, definitions in _PROGRESS_COLLECTIONS.items():
            result = self.provider_results.get(domain)
            if result is None or result.status not in _READABLE or not isinstance(result.data, Mapping):
                continue
            for collection, label, title_fields in definitions:
                rows = result.data.get(collection, ())
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, Mapping):
                        continue
                    source_id = str(row.get("id", "") or "").strip()
                    if not source_id:
                        continue
                    items.append(
                        {
                            "key": f"{domain}:{collection}:{source_id}",
                            "sourceDomain": domain,
                            "sourceType": collection,
                            "sourceId": source_id,
                            "name": _first(row, title_fields, label),
                            "category": label,
                            "status": str(row.get("status", "") or "PENDING").upper(),
                            "updatedAt": row.get("updatedAt") or row.get("createdAt"),
                            "actionRoute": self.routes.get(domain),
                        }
                    )
        return sorted(
            items,
            key=lambda item: (item.get("updatedAt") or "", item["key"]),
            reverse=True,
        )[:200]
