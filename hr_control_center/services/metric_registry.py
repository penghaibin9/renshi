"""
hr_control_center/services/metric_registry.py

MetricDefinitionRegistry —— 每个 KPI 都有定义、版本、时间口径、新鲜度合同。

硬合同（总册 17 / 19 节）：
- cacheTtlSeconds ≠ maxStaleSeconds ≠ hardExpireSeconds，三者不能混为一谈。
- UNAVAILABLE / ERROR / STALE 绝不能转成 0。
- 公式语义变化必须提高 definition_version。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# 指标状态（总册 7.1）
OK = "OK"
PARTIAL = "PARTIAL"
UNAVAILABLE = "UNAVAILABLE"
STALE = "STALE"
ERROR = "ERROR"

FRESHNESS_STATES = (OK, PARTIAL, UNAVAILABLE, STALE, ERROR)


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    name: str
    definition: str  # 业务定义（中文）
    definition_version: str
    unit: str
    owner_domain: str
    source_domains: tuple
    sensitivity: str = "NORMAL"  # NORMAL / SENSITIVE
    supported_scopes: tuple = ("SCHOOL", "COLLEGE", "DEPARTMENT")
    cache_ttl_seconds: int = 60
    max_stale_seconds: int = 180
    hard_expire_seconds: int = 900
    serve_stale_on_error: bool = True
    freshness_mode: str = "EVENT_OR_TTL"


# 高校人事 KPI 字典 V1（总册第 8 节）
METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    "active_headcount": MetricDefinition(
        key="active_headcount",
        name="在岗教职工",
        definition="as_of 日期存在有效 EmploymentRelation 且状态计入在岗口径的唯一教职工人数。"
        "不使用当前 Employee.is_active 代替历史事实。",
        definition_version="1.0",
        unit="person",
        owner_domain="hr03",
        source_domains=("hr03",),
        cache_ttl_seconds=60,
        max_stale_seconds=180,
        hard_expire_seconds=900,
        serve_stale_on_error=True,
    ),
    "full_time_teacher": MetricDefinition(
        key="full_time_teacher",
        name="专任教师",
        definition="在岗人员中，当前/指定日期主人员类别属于学校配置的 FULL_TIME_TEACHER 口径。",
        definition_version="1.0",
        unit="person",
        owner_domain="hr03",
        source_domains=("hr03",),
        cache_ttl_seconds=60,
        max_stale_seconds=180,
        hard_expire_seconds=900,
        serve_stale_on_error=True,
    ),
    "double_teacher_valid": MetricDefinition(
        key="double_teacher_valid",
        name="双师型有效人数",
        definition="as_of 日期存在有效双师认定，未过期/未撤销。HR09 未建设时 UNAVAILABLE，不能显示 0。",
        definition_version="1.0",
        unit="person",
        owner_domain="hr09",
        source_domains=("hr09",),
        cache_ttl_seconds=300,
        max_stale_seconds=600,
        hard_expire_seconds=3600,
        serve_stale_on_error=True,
    ),
    "new_join_ytd": MetricDefinition(
        key="new_join_ytd",
        name="本年新进",
        definition="统计年度内 EmploymentRelation 首次正式生效人数。periodCalendar=CALENDAR_YEAR。",
        definition_version="1.0",
        unit="person",
        owner_domain="hr03",
        source_domains=("hr03",),
        cache_ttl_seconds=300,
        max_stale_seconds=600,
        hard_expire_seconds=3600,
        serve_stale_on_error=True,
    ),
    "departure_ytd": MetricDefinition(
        key="departure_ytd",
        name="本年离退",
        definition="统计年度内正式离职 + 调出 + 退休等退出在岗口径的人数。可在钻取中区分原因。",
        definition_version="1.0",
        unit="person",
        owner_domain="hr03",
        source_domains=("hr03",),
        cache_ttl_seconds=300,
        max_stale_seconds=600,
        hard_expire_seconds=3600,
        serve_stale_on_error=True,
    ),
    "open_risk_count": MetricDefinition(
        key="open_risk_count",
        name="待处理风险",
        definition="当前用户有权限看到，严重度 HIGH/CRITICAL 且状态 OPEN 的预警实例数量。",
        definition_version="1.0",
        unit="item",
        owner_domain="hr01",
        source_domains=("hr01",),
        sensitivity="NORMAL",
        supported_scopes=("SCHOOL", "COLLEGE", "DEPARTMENT", "ASSIGNED"),
        cache_ttl_seconds=15,
        max_stale_seconds=30,
        hard_expire_seconds=120,
        serve_stale_on_error=False,
    ),
    # ---- HR08 外聘教师（总册 §132 可观测性）----
    "hr08_active_engagements": MetricDefinition(
        key="hr08_active_engagements",
        name="活跃外聘聘期",
        definition="当前 as_of 状态为 ACTIVE/REVIEW_DUE/RENEWAL_IN_PROGRESS/SIGNED_WAITING_EFFECTIVE/SUSPENDED 的外聘聘期数。",
        definition_version="1.0",
        unit="item",
        owner_domain="hr08",
        source_domains=("hr08",),
        supported_scopes=("SCHOOL", "COLLEGE", "ORGANIZATION"),
        cache_ttl_seconds=60,
        max_stale_seconds=180,
        hard_expire_seconds=900,
        serve_stale_on_error=True,
    ),
    "hr08_engagements_expiring": MetricDefinition(
        key="hr08_engagements_expiring",
        name="90 日内到期聘期",
        definition="当前 active 聘期中，end_at 落在未来 90 天内的数量（进入续聘评估窗口，§59）。",
        definition_version="1.0",
        unit="item",
        owner_domain="hr08",
        source_domains=("hr08",),
        supported_scopes=("SCHOOL", "COLLEGE", "ORGANIZATION"),
        cache_ttl_seconds=60,
        max_stale_seconds=180,
        hard_expire_seconds=900,
        serve_stale_on_error=True,
    ),
    "hr08_tasks_overdue": MetricDefinition(
        key="hr08_tasks_overdue",
        name="超期任务",
        definition="外聘教学与服务任务中，计划结束日已过且仍处于 ASSIGNED/ACCEPTED/IN_PROGRESS 的任务数。",
        definition_version="1.0",
        unit="item",
        owner_domain="hr08",
        source_domains=("hr08",),
        supported_scopes=("SCHOOL", "COLLEGE", "ORGANIZATION"),
        cache_ttl_seconds=60,
        max_stale_seconds=180,
        hard_expire_seconds=900,
        serve_stale_on_error=True,
    ),
    "hr08_workload_unverified": MetricDefinition(
        key="hr08_workload_unverified",
        name="待核验工作量",
        definition="外聘工作量记录中 verification_status=UNVERIFIED 的数量（§52 本人提交不自动成为正式数量）。",
        definition_version="1.0",
        unit="item",
        owner_domain="hr08",
        source_domains=("hr08",),
        supported_scopes=("SCHOOL", "COLLEGE", "ORGANIZATION"),
        cache_ttl_seconds=60,
        max_stale_seconds=180,
        hard_expire_seconds=900,
        serve_stale_on_error=True,
    ),
    "hr08_industry_experts": MetricDefinition(
        key="hr08_industry_experts",
        name="产业专家",
        definition="外聘档案中 primary_category 属于产业教授/产业兼职/技能大师/产业导师的当前人数。",
        definition_version="1.0",
        unit="person",
        owner_domain="hr08",
        source_domains=("hr08",),
        supported_scopes=("SCHOOL", "COLLEGE", "ORGANIZATION"),
        cache_ttl_seconds=300,
        max_stale_seconds=600,
        hard_expire_seconds=3600,
        serve_stale_on_error=True,
    ),
    "hr08_renewals_due": MetricDefinition(
        key="hr08_renewals_due",
        name="30 日内续聘评估",
        definition="续聘评估单中 status 未决（DRAFT/IN_REVIEW）且 review_due_at 在未来 30 天内的数量（§59）。",
        definition_version="1.0",
        unit="item",
        owner_domain="hr08",
        source_domains=("hr08",),
        supported_scopes=("SCHOOL", "COLLEGE", "ORGANIZATION"),
        cache_ttl_seconds=60,
        max_stale_seconds=180,
        hard_expire_seconds=900,
        serve_stale_on_error=True,
    ),
}


class MetricDefinitionRegistry:
    """
    代码级指标注册表（V1 不做可视化 SQL 编辑器）。

    - get(): 按 key 取定义；
    - all(): 全量；
    - 每次响应必须携带 definitionVersion，避免“同名 KPI 含义已变却无法追溯”。
    """

    def __init__(self, definitions: Optional[dict] = None):
        self._definitions = dict(definitions or METRIC_DEFINITIONS)

    def get(self, key: str) -> Optional[MetricDefinition]:
        return self._definitions.get(key)

    def all(self) -> dict:
        return dict(self._definitions)

    def register(self, definition: MetricDefinition):
        self._definitions[definition.key] = definition


_registry: Optional[MetricDefinitionRegistry] = None


def get_registry() -> MetricDefinitionRegistry:
    global _registry
    if _registry is None:
        _registry = MetricDefinitionRegistry()
    return _registry
