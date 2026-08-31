"""
hr_control_center/selectors/alert.py

HR01-03 人事预警只读查询 —— 接受已解析的 HrRequestContext，返回 DTO（dict），不 render HTML，不写库。

硬合同（总册 11 / 22 节）：
- “今天/逾期/今日新增”一律基于 context 的学校时区，禁止 date.today() / datetime.now() 直用。
- 无学校上下文 → fail-closed（HrContextError），不允许跨校合并出无意义列表。
- HrAlertInstance.objects 是普通 Manager（无公司过滤），必须显式按 tenant_id 过滤。
- 排序契约：CRITICAL 优先 → 逾期优先 → due_at 升序（null 最后）。
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional

from django.db.models import Count

from hr_control_center.context import HrContextError, HrRequestContext
from hr_control_center.models import HrAlertInstance

# 活跃（未终结）状态 —— 列表/统计的默认口径
ACTIVE_ALERT_STATUSES = ("OPEN", "ACKNOWLEDGED", "SNOOZED")

# 严重度排序（总册 11.2），CRITICAL 排最前
SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITY_ORDER)}


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


class AlertSelector:
    """人事预警只读查询。"""

    def __init__(self, context: HrRequestContext):
        self.context = context

    # ---- 基础 -------------------------------------------------------------

    def _require_tenant(self):
        if not self.context.tenant_id:
            raise HrContextError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")

    def _base_qs(self):
        self._require_tenant()
        return HrAlertInstance.objects.filter(tenant_id=self.context.tenant_id)

    def _now(self) -> datetime:
        return self.context.now()

    # ---- 查询 -------------------------------------------------------------

    def list_alerts(self, filters: Optional[dict] = None) -> dict:
        """
        风险列表。

        filters（均可选）：
          - status:       单个或列表，默认 ACTIVE_ALERT_STATUSES
          - severity:     单个或列表，如 "HIGH" / ["CRITICAL","HIGH"]
          - category:     source_domain 单个或列表（别名 source_domain），如 "contract"/"retirement"/"data_quality"
          - alert_key:    按规则过滤，如 "contract.expire_90d"
          - overdue:      True 只返回已逾期（due_at < now 且非空）
          - limit/offset: 简单分页

        排序：CRITICAL 优先 → 逾期优先 → due_at 升序（null 最后）。
        """
        filters = dict(filters or {})
        now = self._now()
        qs = self._base_qs()

        statuses = filters.get("status") or ACTIVE_ALERT_STATUSES
        if isinstance(statuses, str):
            statuses = [statuses]
        qs = qs.filter(status__in=statuses)

        severity = filters.get("severity")
        if severity:
            if isinstance(severity, str):
                severity = [severity]
            qs = qs.filter(severity__in=severity)

        category = filters.get("category") or filters.get("source_domain")
        if category:
            if isinstance(category, str):
                category = [category]
            qs = qs.filter(source_domain__in=category)

        alert_key = filters.get("alert_key")
        if alert_key:
            qs = qs.filter(alert_key=alert_key)

        if filters.get("overdue"):
            qs = qs.filter(due_at__isnull=False, due_at__lt=now)

        rows = list(qs)
        rows.sort(key=lambda r: self._sort_key(r, now))

        total = len(rows)
        offset = filters.get("offset") or 0
        limit = filters.get("limit")
        if limit:
            rows = rows[offset : offset + int(limit)]
        elif offset:
            rows = rows[offset:]

        return {
            "items": [self._to_dto(r, now) for r in rows],
            "total": total,
            "count": len(rows),
        }

    def get_detail(self, instance_id: int) -> Optional[dict]:
        """单条风险详情（详情面板用）。不存在返回 None。"""
        inst = self._base_qs().filter(pk=instance_id).first()
        if inst is None:
            return None
        return self._to_dto(inst, self._now())

    def get_summary(self) -> dict:
        """
        顶部统计（总册 11.5）：严重｜高｜中｜低｜提示｜今日新增｜已逾期｜按分类｜按状态。
        口径：status ∈ ACTIVE_ALERT_STATUSES 的实例。
        """
        now = self._now()
        qs = self._base_qs().filter(status__in=ACTIVE_ALERT_STATUSES)

        by_severity = {s: 0 for s in SEVERITY_ORDER}
        for row in qs.values("severity").annotate(n=Count("id")):
            sev = row["severity"]
            if sev in by_severity:
                by_severity[sev] = row["n"]

        by_status = {s: 0 for s in HrAlertInstance.Status.values}
        for row in qs.values("status").annotate(n=Count("id")):
            st = row["status"]
            if st in by_status:
                by_status[st] = row["n"]

        by_category = {}
        for row in qs.values("source_domain").annotate(n=Count("id")):
            by_category[row["source_domain"]] = row["n"]

        today_start = datetime.combine(
            self.context.today(), time(0, 0), tzinfo=self.context.tzinfo()
        )
        today_new = (
            qs.filter(first_seen_at__gte=today_start)
            .count()
        )
        overdue = (
            qs.filter(due_at__isnull=False, due_at__lt=now)
            .count()
        )

        return {
            "bySeverity": by_severity,
            "critical": by_severity["CRITICAL"],
            "high": by_severity["HIGH"],
            "medium": by_severity["MEDIUM"],
            "low": by_severity["LOW"],
            "info": by_severity["INFO"],
            "byStatus": by_status,
            "byCategory": by_category,
            "todayNew": today_new,
            "overdue": overdue,
            "activeTotal": len(qs),
        }

    def open_risk_count(self) -> int:
        """open_risk_count KPI：HIGH/CRITICAL 且 OPEN 的实例数（总册 8.1）。"""
        return (
            self._base_qs()
            .filter(status=HrAlertInstance.Status.OPEN, severity__in=["HIGH", "CRITICAL"])
            .count()
        )

    # ---- DTO / 排序 -------------------------------------------------------

    @staticmethod
    def _sort_key(row, now: datetime):
        rank = SEVERITY_RANK.get(row.severity, len(SEVERITY_RANK))
        overdue = 0 if (row.due_at and row.due_at < now) else 1
        due = row.due_at if row.due_at else datetime.max.replace(tzinfo=now.tzinfo())
        return (rank, overdue, due)

    @staticmethod
    def _to_dto(inst: HrAlertInstance, now: datetime) -> dict:
        return {
            "id": inst.pk,
            "alertKey": inst.alert_key,
            "category": inst.source_domain,
            "sourceDomain": inst.source_domain,
            "sourceObjectType": inst.source_object_type,
            "sourceObjectId": inst.source_object_id,
            "dedupeKey": inst.dedupe_key,
            "title": inst.title,
            "summary": inst.summary,
            "severity": inst.severity,
            "status": inst.status,
            "firstSeenAt": _iso(inst.first_seen_at),
            "lastSeenAt": _iso(inst.last_seen_at),
            "dueAt": _iso(inst.due_at),
            "overdue": bool(inst.due_at and inst.due_at < now),
            "ownerRole": inst.owner_role,
            "ownerUserId": inst.owner_user_id,
            "payload": inst.payload_json,
            "createdAt": _iso(inst.created_at),
            "resolvedAt": _iso(inst.resolved_at),
            "resolvedReason": inst.resolved_reason,
        }
