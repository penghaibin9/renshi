"""
hr_control_center/services/alert_service.py

HR01-03 人事预警服务（S5）—— 规则执行 + dedupe upsert + 状态流转 + 审计。

硬合同（总册 11 / S5 / 24 节）：
- LEGACY_ONLY 阶段只基于 Horilla 真实数据源（Employee / EmployeeWorkInformation）产出预警，
  未建设业务域（workflow 审批 / HR09 双师资格）不做，绝不为凑数制造假预警。
- 禁止 fake-zero：规则失败 → UNAVAILABLE/ERROR 或跳过并记录 reasonCode，不假装“没有风险”。
- 禁止 except Exception: pass；规则/写库异常必须抛出 HrProviderError（含追踪字段）或显式上报。
- 禁止 date.today() / datetime.now() 直用，一律走 context.today() / context.now()（学校时区）。
- dedupe：UNIQUE(tenant, dedupe_key, status∈OPEN/ACKNOWLEDGED/SNOOZED) 由 DB 约束保证，
  service 层实现 upsert 语义（先查已有非终结实例，存在则刷新 last_seen_at 等事实，不存在才 create）。
- 公司过滤：走 HorillaCompanyManager（当前选中学校），不在 service 里手动拼 tenant 过滤。
- 写操作（ack/snooze）用 select_for_update + 状态校验处理并发；模型无版本字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from dateutil.relativedelta import relativedelta
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.dateparse import parse_date, parse_datetime

from hr_control_center.context import HrContextError, HrRequestContext
from hr_control_center.models import HrAlertInstance
from hr_control_center.providers.base import (
    AUTHORITY_ONLY,
    DATA_BASIS_LEGACY_CURRENT_SNAPSHOT,
    HrProviderError,
    LEGACY_ONLY,
)
from hr_control_center.selectors.alert import (
    ACTIVE_ALERT_STATUSES,
    SEVERITY_ORDER,
    AlertSelector,
)
from hr_control_center.services.metric_registry import ERROR, OK, UNAVAILABLE

# snooze 最大窗口（“SNOOZED 必须限最大期限”）
MAX_SNOOZE_DAYS = 30

# V1 规则参数化配置（提前天数 / severity / enabled 都从这里读，不写死在规则代码里）。
# 分类（category = source_domain）对齐页面 Tab：contract / retirement / qualification /
# workflow / data_quality / structure。
ALERT_RULE_CONFIG = {
    "contract.expire_90d": {
        "enabled": True,
        "source_domain": "contract",
        "lookahead_days": 90,
        # 剩余天数 <= 30 且无续签事实 → HIGH；<= 90 → MEDIUM
        "severity_cutoffs": [(30, "HIGH"), (90, "MEDIUM")],
        # 到期日后仍未续签（仍在窗口内）→ 升级为过期风险，避免被误标“已解决”
        "overdue_window_days": 90,
        "overdue_severity": "HIGH",
    },
    "retirement.within_180d": {
        "enabled": True,
        "source_domain": "retirement",
        "lookahead_days": 180,
        # Legacy 无“接替安排”事实：30 天内无法确认无接替，不冒领 HIGH（避免假预警），
        # 30 天内 → MEDIUM；90/180 天内 → INFO。HIGH 待接替事实源（HR04/后续）就绪后再启用。
        "severity_cutoffs": [(30, "MEDIUM"), (90, "INFO"), (180, "INFO")],
        "retirement_age": {"male": 60, "female": 55},
        # 已达退休年龄但仍未离岗（窗口内）→ 升级为过期风险，避免被误标“已解决”
        "overdue_window_days": 180,
        "overdue_severity": "HIGH",
    },
    "staff.required_field_missing": {
        "enabled": True,
        "source_domain": "data_quality",
        "required_fields": ["department_id", "job_position_id", "employee_type_id"],
        "required_field_labels": {
            "department_id": "部门",
            "job_position_id": "岗位",
            "employee_type_id": "人员类别",
        },
        "sample_size": 5,
        "severity": "MEDIUM",
        "high_ratio_threshold": 0.1,  # 缺失率 >= 10% 升级 HIGH
    },
    # ---- LEGACY 阶段明确不实现（总册 11.6 / S5：“不做”并记录原因，不生成假预警）----
    "workflow.overdue": {
        "enabled": False,
        "reason": "审批流程状态在 Legacy 阶段无法确认，避免假预警",
    },
    "hr09.certificate_expiry": {
        "enabled": False,
        "reason": "HR09 双师/资格模块未建设，无真实数据源",
    },
}


class AlertServiceError(Exception):
    """预警 service 层业务错误（ack/snooze 校验、权限、并发冲突）。"""

    def __init__(self, code: str, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


@dataclass
class AlertCandidate:
    """单条预警候选（规则输出单元，可序列化）。"""

    source_object_type: str
    source_object_id: str
    title: str
    summary: str
    severity: str
    due_at: Optional[datetime] = None
    payload: dict = field(default_factory=dict)
    owner_role: str = ""
    owner_user_id: Optional[int] = None
    dedupe_extra: str = ""

    def to_dict(self) -> dict:
        return {
            "sourceObjectType": self.source_object_type,
            "sourceObjectId": self.source_object_id,
            "title": self.title,
            "summary": self.summary,
            "severity": self.severity,
            "dueAt": self.due_at.isoformat() if self.due_at else None,
            "payload": self.payload,
        }


@dataclass
class RuleResult:
    """规则执行结果（可序列化）。status=OK 携带候选；UNAVAILABLE/ERROR 携带 reasonCode。"""

    alert_key: str
    source_domain: str
    status: str = OK
    items: List[AlertCandidate] = field(default_factory=list)
    reason_code: Optional[str] = None
    message: Optional[str] = None
    definition_version: str = "1.0"

    def to_dict(self) -> dict:
        return {
            "alertKey": self.alert_key,
            "sourceDomain": self.source_domain,
            "status": self.status,
            "reasonCode": self.reason_code,
            "message": self.message,
            "candidateCount": len(self.items),
            "candidates": [i.to_dict() for i in self.items],
        }


# ---- 数据源辅助（公司过滤由 HorillaCompanyManager 自动完成） -------------


def _emp_model():
    from employee.models import Employee

    return Employee


def _work_info_model():
    from employee.models import EmployeeWorkInformation

    return EmployeeWorkInformation


def _employee_label(employee) -> str:
    if employee is None:
        return "?"
    name = employee.get_full_name()
    badge = employee.badge_id or ""
    return f"{name} ({badge})" if badge else name


def _department_label(work_info) -> Optional[str]:
    if work_info and work_info.department_id:
        return work_info.department_id.department
    return None


def _job_position_label(work_info) -> Optional[str]:
    if work_info and work_info.job_position_id:
        return work_info.job_position_id.job_position
    return None


def _end_of_day(context: HrRequestContext, d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59), tzinfo=context.tzinfo())


def _severity_for_days(days_left: int, cutoffs) -> str:
    """按剩余天数取 severity；cutoffs 按 max_days 升序，第一个命中生效。"""
    for max_days, severity in cutoffs:
        if days_left <= max_days:
            return severity
    return "INFO"


# ---- V1 规则（只做能确认真实数据源的） ------------------------------------


def _rule_contract_expire_90d(context: HrRequestContext, config: dict) -> RuleResult:
    """
    contract.expire_90d —— EmployeeWorkInformation.contract_end_date 在未来 90 天内到期。

    Legacy 快照无“续签”事实：contract_end_date 未变化即视为未续签，30 天内 → HIGH，90 天内 → MEDIUM。
    到期日后仍未续签（在 overdue_window_days 窗口内）→ 升级为 overdue_severity（默认 HIGH），
    同 dedupe_key 持续存活，直到真正续签（截止日移出窗口）或员工离岗才被 service 标为已解决，
    避免把“合同已过期”误标成 RISK_CLEARED。payload 中 renewalStatus=UNKNOWN_FROM_LEGACY 如实标注。
    """
    lookahead_days = int(config.get("lookahead_days", 90))
    overdue_window_days = int(config.get("overdue_window_days", lookahead_days))
    overdue_severity = config.get("overdue_severity", "HIGH")
    cutoffs = config.get(
        "severity_cutoffs", [(30, "HIGH"), (90, "MEDIUM")]
    )
    source_domain = config.get("source_domain", "contract")
    today = context.today()
    horizon = today + timedelta(days=lookahead_days)
    past = today - timedelta(days=overdue_window_days)
    try:
        qs = (
            _work_info_model()
            .objects.filter(
                employee_id__is_active=True,
                contract_end_date__isnull=False,
                contract_end_date__gte=past,
                contract_end_date__lte=horizon,
            )
            .select_related("employee_id", "department_id", "job_position_id")
            .order_by("contract_end_date")
        )
        items = []
        for wi in qs.iterator():
            employee = wi.employee_id
            days_left = (wi.contract_end_date - today).days
            label = _employee_label(employee)
            if days_left >= 0:
                severity = _severity_for_days(days_left, cutoffs)
                title = f"合同将于 {wi.contract_end_date.isoformat()} 到期"
                summary = (
                    f"{label} 的合同将于 {wi.contract_end_date.isoformat()} 到期，"
                    f"剩余 {days_left} 天，尚未确认续签。"
                )
            else:
                severity = overdue_severity
                title = f"合同已于 {wi.contract_end_date.isoformat()} 到期（已过期）"
                summary = (
                    f"{label} 的合同已于 {wi.contract_end_date.isoformat()} 到期，"
                    f"已过期 {-days_left} 天，仍未续签。"
                )
            items.append(
                AlertCandidate(
                    source_object_type="employee_work_info",
                    source_object_id=str(wi.pk),
                    title=title,
                    summary=summary,
                    severity=severity,
                    due_at=_end_of_day(context, wi.contract_end_date),
                    payload={
                        "employee": {
                            "id": employee.pk if employee else None,
                            "name": label,
                            "badgeId": employee.badge_id if employee else "",
                        },
                        "contractEndDate": wi.contract_end_date.isoformat(),
                        "daysLeft": days_left,
                        "department": _department_label(wi),
                        "jobPosition": _job_position_label(wi),
                        "renewalStatus": "UNKNOWN_FROM_LEGACY",
                        "dataBasis": DATA_BASIS_LEGACY_CURRENT_SNAPSHOT,
                    },
                )
            )
        return RuleResult(
            alert_key="contract.expire_90d",
            source_domain=source_domain,
            status=OK,
            items=items,
        )
    except HrProviderError:
        raise
    except Exception as exc:
        raise HrProviderError(
            "legacy_alert",
            "contract.expire_90d",
            "CONTRACT_EXPIRE_SCAN_FAILED",
            str(exc),
            tenant_id=context.tenant_id,
            scope_fingerprint=context.scope_fingerprint(),
        ) from exc


def _rule_retirement_within_180d(context: HrRequestContext, config: dict) -> RuleResult:
    """
    retirement.within_180d —— 由 dob 推算退休年龄（男 60 / 女 55）在未来 180 天内。

    - dob 为空 → 跳过（不报错）；性别无法判定退休年龄 → 跳过；超过退休年龄且超出窗口 → 跳过。
    - Legacy 无“接替岗位安排”事实，30 天内不冒领 HIGH（避免假预警），见配置说明。
    - 已达退休年龄但仍未离岗（窗口内）→ 升级为 overdue_severity（默认 HIGH），
      同 dedupe_key 持续存活，直到员工离岗才被 service 标为已解决。
    """
    lookahead_days = int(config.get("lookahead_days", 180))
    overdue_window_days = int(config.get("overdue_window_days", lookahead_days))
    overdue_severity = config.get("overdue_severity", "HIGH")
    cutoffs = config.get(
        "severity_cutoffs", [(30, "MEDIUM"), (90, "INFO"), (180, "INFO")]
    )
    ages = config.get("retirement_age", {"male": 60, "female": 55})
    source_domain = config.get("source_domain", "retirement")
    today = context.today()
    past = today - timedelta(days=overdue_window_days)
    try:
        qs = _emp_model().objects.filter(is_active=True).select_related("employee_work_info")
        items = []
        skipped_missing_dob = 0
        skipped_unknown_gender = 0
        skipped_past_window = 0
        for emp in qs.iterator():
            if not emp.dob:
                skipped_missing_dob += 1
                continue
            gender = emp.gender
            if gender not in ages:
                skipped_unknown_gender += 1
                continue
            retirement_date = emp.dob + relativedelta(years=ages[gender])
            days_left = (retirement_date - today).days
            if days_left < -overdue_window_days:
                skipped_past_window += 1
                continue
            if days_left > lookahead_days:
                continue
            label = _employee_label(emp)
            if days_left >= 0:
                severity = _severity_for_days(days_left, cutoffs)
                title = f"{label} 将于 {retirement_date.isoformat()} 达到退休年龄"
                summary = (
                    f"{label} 预计 {retirement_date.isoformat()} 达到退休年龄"
                    f"（{ages[gender]} 岁），剩余 {days_left} 天。"
                )
            else:
                severity = overdue_severity
                title = f"{label} 已超过退休年龄 {retirement_date.isoformat()}（应退休）"
                summary = (
                    f"{label} 已于 {retirement_date.isoformat()} 达到退休年龄"
                    f"（{ages[gender]} 岁），已过 {-days_left} 天仍未办理离岗。"
                )
            items.append(
                AlertCandidate(
                    source_object_type="employee",
                    source_object_id=str(emp.pk),
                    title=title,
                    summary=summary,
                    severity=severity,
                    due_at=_end_of_day(context, retirement_date),
                    payload={
                        "employee": {
                            "id": emp.pk,
                            "name": label,
                            "badgeId": emp.badge_id or "",
                        },
                        "retirementDate": retirement_date.isoformat(),
                        "retirementAge": ages[gender],
                        "gender": gender,
                        "daysLeft": days_left,
                        "department": _department_label(emp.employee_work_info),
                        "jobPosition": _job_position_label(emp.employee_work_info),
                        "successorStatus": "UNKNOWN_FROM_LEGACY",
                        "dataBasis": DATA_BASIS_LEGACY_CURRENT_SNAPSHOT,
                    },
                )
            )
        message = None
        if skipped_missing_dob or skipped_unknown_gender or skipped_past_window:
            message = (
                f"跳过：缺出生日期 {skipped_missing_dob} 人、无法判定退休年龄 "
                f"{skipped_unknown_gender} 人、超过退休年龄且超出窗口 {skipped_past_window} 人。"
            )
        return RuleResult(
            alert_key="retirement.within_180d",
            source_domain=source_domain,
            status=OK,
            items=items,
            message=message,
        )
    except HrProviderError:
        raise
    except Exception as exc:
        raise HrProviderError(
            "legacy_alert",
            "retirement.within_180d",
            "RETIREMENT_SCAN_FAILED",
            str(exc),
            tenant_id=context.tenant_id,
            scope_fingerprint=context.scope_fingerprint(),
        ) from exc


def _rule_staff_required_field_missing(
    context: HrRequestContext, config: dict
) -> RuleResult:
    """
    staff.required_field_missing —— 数据型：在岗员工缺部门/岗位/人员类别关键字段。

    聚合为单条预警（source_object_type=aggregate），不逐人生成，避免告警风暴。
    缺失人数为 0 → 空 items（由 service 负责把旧实例标记 RESOLVED）。
    """
    required_fields = config.get(
        "required_fields", ["department_id", "job_position_id", "employee_type_id"]
    )
    labels = config.get(
        "required_field_labels",
        {"department_id": "部门", "job_position_id": "岗位", "employee_type_id": "人员类别"},
    )
    sample_size = int(config.get("sample_size", 5))
    base_severity = config.get("severity", "MEDIUM")
    high_ratio_threshold = float(config.get("high_ratio_threshold", 0.1))
    source_domain = config.get("source_domain", "data_quality")
    try:
        active = _emp_model().objects.filter(is_active=True)
        total_active = active.count()

        union_q = Q(employee_work_info__isnull=True)
        counts: dict = {}
        samples: dict = {}
        for field in required_fields:
            field_q = Q(employee_work_info__isnull=True) | Q(
                **{f"employee_work_info__{field}__isnull": True}
            )
            union_q |= Q(**{f"employee_work_info__{field}__isnull": True})
            qs = active.filter(field_q).distinct()
            counts[field] = qs.count()
            rows = list(
                qs.order_by("employee_first_name", "employee_last_name")[:sample_size]
                .values_list("employee_first_name", "employee_last_name", "badge_id")
            )
            sample_names = []
            for first, last, badge in rows:
                name = f"{first} {last}".strip() if last else first
                if badge:
                    name = f"{name} ({badge})"
                sample_names.append(name)
            samples[field] = sample_names

        missing_any = active.filter(union_q).distinct().count()

        items = []
        if missing_any > 0:
            ratio = missing_any / total_active if total_active else 0.0
            severity = base_severity
            if ratio >= high_ratio_threshold:
                severity = "HIGH"
            summary_parts = "、".join(
                f"{labels.get(f, f)} {counts[f]}人" for f in required_fields
            )
            items.append(
                AlertCandidate(
                    source_object_type="aggregate",
                    source_object_id=f"tenant_{context.tenant_id}",
                    title="在岗员工关键档案缺失",
                    summary=f"在岗 {total_active} 人中 {missing_any} 人关键档案缺失：{summary_parts}。",
                    severity=severity,
                    due_at=None,
                    payload={
                        "totalActive": total_active,
                        "missingAny": missing_any,
                        "counts": {labels.get(f, f): counts[f] for f in required_fields},
                        "samples": {labels.get(f, f): samples[f] for f in required_fields},
                        "requiredFields": required_fields,
                        "dataBasis": DATA_BASIS_LEGACY_CURRENT_SNAPSHOT,
                    },
                )
            )
        return RuleResult(
            alert_key="staff.required_field_missing",
            source_domain=source_domain,
            status=OK,
            items=items,
        )
    except HrProviderError:
        raise
    except Exception as exc:
        raise HrProviderError(
            "legacy_alert",
            "staff.required_field_missing",
            "REQUIRED_FIELD_SCAN_FAILED",
            str(exc),
            tenant_id=context.tenant_id,
            scope_fingerprint=context.scope_fingerprint(),
        ) from exc


ALERT_RULES = {
    "contract.expire_90d": _rule_contract_expire_90d,
    "retirement.within_180d": _rule_retirement_within_180d,
    "staff.required_field_missing": _rule_staff_required_field_missing,
}


def _validate_rule_config():
    """配置自检：severity 必须属于合法集合，避免脏数据写库。"""
    for key, cfg in ALERT_RULE_CONFIG.items():
        for _, severity in cfg.get("severity_cutoffs", []):
            if severity not in SEVERITY_ORDER:
                raise ValueError(f"{key}: 非法 severity {severity}")


_validate_rule_config()


class AlertService:
    """
    HR01-03 人事预警服务。

    读（list_alerts / get_summary / open_risk_count）委托只读 AlertSelector；
    写（run_rules / acknowledge / snooze）在本类实现 upsert、状态流转与审计。
    """

    # ---- 规则执行 ---------------------------------------------------------

    def run_rules(
        self,
        context: HrRequestContext,
        *,
        dry_run: bool = False,
        rule_keys: Optional[List[str]] = None,
    ) -> dict:
        """
        执行已启用的预警规则，扫描真实数据并 upsert HrAlertInstance。

        语义：
          - 同一 tenant+dedupe_key（= rule+对象+截止日）的非终结实例已存在 → 只刷新
            last_seen_at 与标题/摘要/严重度/due_at 等事实，不重复创建；
          - 本次规则成功运行后，该规则下未再命中（风险消除）的旧实例 → RESOLVED(RISK_CLEARED)；
          - 规则失败/未启用/业务域未建设 → 上报 reasonCode，绝不假装“没有风险”，
            且不触碰该规则的既有实例；
          - dry_run=True 只扫描计算，不做任何写库。
        """
        self._require_tenant(context)
        now = context.now()
        authority_mode = context.authority_mode or LEGACY_ONLY
        rule_keys = set(rule_keys) if rule_keys else None

        rule_report: List[dict] = []
        totals = {"created": 0, "updated": 0, "resolved": 0, "skipped": 0}
        errors: List[dict] = []

        for key, config in ALERT_RULE_CONFIG.items():
            if rule_keys is not None and key not in rule_keys:
                continue

            if not config.get("enabled", True):
                rule_report.append(
                    {
                        "alertKey": key,
                        "status": "DISABLED",
                        "reasonCode": "RULE_DISABLED",
                        "message": config.get("reason", "规则未启用"),
                    }
                )
                continue

            fn = ALERT_RULES.get(key)
            if fn is None:
                errors.append(
                    {"alertKey": key, "reasonCode": "RULE_NOT_IMPLEMENTED", "message": "规则未实现"}
                )
                rule_report.append(
                    {
                        "alertKey": key,
                        "status": ERROR,
                        "reasonCode": "RULE_NOT_IMPLEMENTED",
                        "message": "规则未实现",
                    }
                )
                totals["skipped"] += 1
                continue

            if authority_mode == AUTHORITY_ONLY:
                errors.append(
                    {
                        "alertKey": key,
                        "reasonCode": "LEGACY_SOURCE_DISABLED",
                        "message": "AUTHORITY_ONLY 模式下禁用 Legacy 数据源预警",
                    }
                )
                rule_report.append(
                    {
                        "alertKey": key,
                        "status": UNAVAILABLE,
                        "reasonCode": "LEGACY_SOURCE_DISABLED",
                        "message": "AUTHORITY_ONLY 模式下禁用 Legacy 数据源预警",
                    }
                )
                totals["skipped"] += 1
                continue

            try:
                result = fn(context, config)
            except HrProviderError as exc:
                errors.append(
                    {"alertKey": key, "reasonCode": exc.reason_code, "message": str(exc)}
                )
                rule_report.append(
                    {
                        "alertKey": key,
                        "status": ERROR,
                        "reasonCode": exc.reason_code,
                        "message": str(exc),
                    }
                )
                totals["skipped"] += 1
                continue
            except Exception as exc:  # 不吞异常：显式上报为规则崩溃
                errors.append(
                    {"alertKey": key, "reasonCode": "RULE_CRASHED", "message": repr(exc)}
                )
                rule_report.append(
                    {
                        "alertKey": key,
                        "status": ERROR,
                        "reasonCode": "RULE_CRASHED",
                        "message": repr(exc),
                    }
                )
                totals["skipped"] += 1
                continue

            if result.status != OK:
                rule_report.append(result.to_dict())
                totals["skipped"] += 1
                continue

            report = {
                "alertKey": result.alert_key,
                "sourceDomain": result.source_domain,
                "status": result.status,
                "reasonCode": result.reason_code,
                "message": result.message,
                "candidateCount": len(result.items),
                "created": 0,
                "updated": 0,
                "resolved": 0,
            }

            if not dry_run:
                try:
                    with transaction.atomic():
                        seen = set()
                        for item in result.items:
                            dedupe_key = self._build_dedupe_key(
                                result.alert_key, item, context
                            )
                            seen.add(dedupe_key)
                            outcome = self._upsert_instance(
                                context,
                                result.alert_key,
                                result.source_domain,
                                item,
                                dedupe_key,
                                now,
                            )
                            if outcome == "created":
                                report["created"] += 1
                            elif outcome == "updated":
                                report["updated"] += 1
                        report["resolved"] = self._resolve_stale(
                            context, result.alert_key, seen, now
                        )
                except HrProviderError as exc:
                    errors.append(
                        {"alertKey": key, "reasonCode": exc.reason_code, "message": str(exc)}
                    )
                    report.update(status=ERROR, reasonCode=exc.reason_code, message=str(exc))
                except Exception as exc:  # 不吞异常：显式上报
                    errors.append(
                        {"alertKey": key, "reasonCode": "ALERT_WRITE_FAILED", "message": repr(exc)}
                    )
                    report.update(status=ERROR, reasonCode="ALERT_WRITE_FAILED", message=repr(exc))

            totals["created"] += report["created"]
            totals["updated"] += report["updated"]
            totals["resolved"] += report["resolved"]
            if report["status"] == ERROR:
                totals["skipped"] += 1
            rule_report.append(report)

        return {
            "context": {
                "tenantId": context.tenant_id,
                "timezone": context.school_timezone,
                "asOf": context.as_of.isoformat() if context.as_of else None,
            },
            "authorityMode": authority_mode,
            "dryRun": bool(dry_run),
            "rules": rule_report,
            "totals": totals,
            "errors": errors,
        }

    # ---- 读（委托只读 selector） ------------------------------------------

    def list_alerts(self, context: HrRequestContext, filters: Optional[dict] = None) -> dict:
        """风险列表；列出前顺带把已过期 snooze 的实例恢复为 OPEN。"""
        self._require_tenant(context)
        self._reactivate_expired_snoozes(context)
        return AlertSelector(context).list_alerts(filters)

    def get_summary(self, context: HrRequestContext) -> dict:
        """顶部统计（严重｜高｜中｜低｜提示｜今日新增｜已逾期）。"""
        self._require_tenant(context)
        self._reactivate_expired_snoozes(context)
        summary = AlertSelector(context).get_summary()
        summary["asOf"] = context.as_of.isoformat() if context.as_of else None
        summary["dataBasis"] = DATA_BASIS_LEGACY_CURRENT_SNAPSHOT
        return summary

    def open_risk_count(self, context: HrRequestContext) -> int:
        """open_risk_count KPI：HIGH/CRITICAL 且 OPEN 的预警数（供 overview provider 接入）。"""
        self._require_tenant(context)
        return AlertSelector(context).open_risk_count()

    # ---- 状态流转（ack/snooze，select_for_update + 状态校验） ---------------

    def acknowledge(self, instance_id: int, context: HrRequestContext) -> dict:
        """
        OPEN/SNOOZED → ACKNOWLEDGED。幂等：已是 ACKNOWLEDGED 直接返回现状。
        已 RESOLVED/EXPIRED 不可 acknowledge。状态变更写入 payload 审计。
        """
        self._require_tenant(context)
        with transaction.atomic():
            inst = self._get_for_update(context, instance_id)
            if inst.status == HrAlertInstance.Status.ACKNOWLEDGED:
                return self._dto(inst)
            if inst.status not in (
                HrAlertInstance.Status.OPEN,
                HrAlertInstance.Status.SNOOZED,
            ):
                raise AlertServiceError(
                    "INVALID_STATUS",
                    f"当前状态 {inst.status} 不支持 acknowledge",
                    http_status=409,
                )
            old_status = inst.status
            inst.status = HrAlertInstance.Status.ACKNOWLEDGED
            self._append_audit(
                inst,
                "acknowledge",
                old_status=old_status,
                new_status=HrAlertInstance.Status.ACKNOWLEDGED,
                at=context.now(),
                by=context.user_id,
            )
            inst.save(update_fields=["status", "payload_json"])
            return self._dto(inst)

    def snooze(
        self,
        instance_id: int,
        context: HrRequestContext,
        until,
    ) -> dict:
        """
        OPEN/ACKNOWLEDGED/SNOOZED → SNOOZED（可重复延长窗口）。

        硬性限制：
          - CRITICAL 不允许 snooze；
          - until 必须晚于当前时间，且最长不超过 MAX_SNOOZE_DAYS 天；
          - 已 RESOLVED/EXPIRED 不允许 snooze。
        """
        self._require_tenant(context)
        now = context.now()
        until_dt = self._parse_until(until, context)
        if until_dt <= now:
            raise AlertServiceError("SNOOZE_PAST", "snooze 截止时间必须晚于当前时间")
        max_until = now + timedelta(days=MAX_SNOOZE_DAYS)
        if until_dt > max_until:
            raise AlertServiceError(
                "SNOOZE_WINDOW_EXCEEDED",
                f"snooze 最长不超过 {MAX_SNOOZE_DAYS} 天",
            )

        with transaction.atomic():
            inst = self._get_for_update(context, instance_id)
            if inst.severity == HrAlertInstance.Severity.CRITICAL:
                raise AlertServiceError(
                    "CRITICAL_SNOOZE_FORBIDDEN", "CRITICAL 级别预警不允许 snooze"
                )
            if inst.status in (
                HrAlertInstance.Status.RESOLVED,
                HrAlertInstance.Status.EXPIRED,
            ):
                raise AlertServiceError(
                    "INVALID_STATUS",
                    f"当前状态 {inst.status} 不支持 snooze",
                    http_status=409,
                )
            old_status = inst.status
            inst.status = HrAlertInstance.Status.SNOOZED
            payload = dict(inst.payload_json or {})
            payload["snooze"] = {
                "until": until_dt.isoformat(),
                "at": now.isoformat(),
                "by": context.user_id,
            }
            inst.payload_json = payload
            self._append_audit(
                inst,
                "snooze",
                old_status=old_status,
                new_status=HrAlertInstance.Status.SNOOZED,
                at=now,
                by=context.user_id,
            )
            inst.save(update_fields=["status", "payload_json"])
            return self._dto(inst)

    # ---- 内部工具 ---------------------------------------------------------

    @staticmethod
    def _require_tenant(context: HrRequestContext):
        if not context.tenant_id:
            raise HrContextError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")

    def _get_for_update(self, context: HrRequestContext, instance_id: int):
        inst = (
            HrAlertInstance.objects.select_for_update()
            .filter(pk=instance_id, tenant_id=context.tenant_id)
            .first()
        )
        if inst is None:
            raise AlertServiceError(
                "ALERT_NOT_FOUND", "预警不存在或不属于当前学校", http_status=404
            )
        return inst

    @staticmethod
    def _build_dedupe_key(alert_key: str, item: AlertCandidate, context: HrRequestContext) -> str:
        parts = [alert_key, item.source_object_type, item.source_object_id]
        if item.due_at is not None:
            local_due = item.due_at
            if local_due.tzinfo is not None:
                local_due = local_due.astimezone(context.tzinfo())
            parts.append(local_due.date().isoformat())
        if item.dedupe_extra:
            parts.append(item.dedupe_extra)
        return ":".join(parts)

    @staticmethod
    def _find_existing(context: HrRequestContext, alert_key: str, dedupe_key: str):
        return (
            HrAlertInstance.objects.filter(
                tenant_id=context.tenant_id,
                alert_key=alert_key,
                dedupe_key=dedupe_key,
                status__in=ACTIVE_ALERT_STATUSES,
            )
            .order_by("first_seen_at")
            .first()
        )

    def _upsert_instance(
        self,
        context: HrRequestContext,
        alert_key: str,
        source_domain: str,
        item: AlertCandidate,
        dedupe_key: str,
        now: datetime,
    ) -> str:
        """先查非终结实例：存在 → 刷新事实与 last_seen_at；不存在 → create（IntegrityError 兜底重查）。"""
        existing = self._find_existing(context, alert_key, dedupe_key)
        if existing is None:
            try:
                with transaction.atomic():  # savepoint：IntegrityError 后外层事务仍可用
                    HrAlertInstance.objects.create(
                        tenant_id=context.tenant_id,
                        alert_key=alert_key,
                        source_domain=source_domain,
                        source_object_type=item.source_object_type,
                        source_object_id=item.source_object_id,
                        dedupe_key=dedupe_key,
                        title=item.title,
                        summary=item.summary,
                        severity=item.severity,
                        status=HrAlertInstance.Status.OPEN,
                        first_seen_at=now,
                        last_seen_at=now,
                        due_at=item.due_at,
                        owner_role=item.owner_role,
                        owner_user_id=item.owner_user_id,
                        payload_json={
                            "facts": dict(item.payload),
                            "audit": [],
                            "snooze": None,
                        },
                    )
                return "created"
            except IntegrityError:
                existing = self._find_existing(context, alert_key, dedupe_key)
                if existing is None:
                    raise

        update_fields = [
            "title",
            "summary",
            "severity",
            "due_at",
            "payload_json",
            "last_seen_at",
        ]
        existing.title = item.title
        existing.summary = item.summary
        existing.severity = item.severity
        existing.due_at = item.due_at
        payload = dict(existing.payload_json or {})
        payload["facts"] = dict(item.payload)
        existing.payload_json = payload
        existing.last_seen_at = now

        if (
            existing.status == HrAlertInstance.Status.SNOOZED
            and self._snooze_expired(existing, now)
        ):
            old_status = existing.status
            existing.status = HrAlertInstance.Status.OPEN
            update_fields.append("status")
            self._append_audit(
                existing,
                "snooze_expired",
                old_status=old_status,
                new_status=HrAlertInstance.Status.OPEN,
                at=now,
                by=context.user_id,
            )
        existing.save(update_fields=update_fields)
        return "updated"

    def _resolve_stale(
        self,
        context: HrRequestContext,
        alert_key: str,
        seen_dedupe_keys: set,
        now: datetime,
    ) -> int:
        """
        风险消除：本次规则成功扫描后，该规则下未被命中的非终结实例 → RESOLVED(RISK_CLEARED)。
        仅对本次成功运行的规则生效，规则失败/跳过时不触碰既有实例（不产生假“已解决”）。
        """
        stale = (
            HrAlertInstance.objects.filter(
                tenant_id=context.tenant_id,
                alert_key=alert_key,
                status__in=ACTIVE_ALERT_STATUSES,
            )
            .exclude(dedupe_key__in=seen_dedupe_keys)
        )
        count = 0
        for inst in stale:
            old_status = inst.status
            inst.status = HrAlertInstance.Status.RESOLVED
            inst.resolved_at = now
            inst.resolved_reason = "RISK_CLEARED"
            inst.last_seen_at = now
            self._append_audit(
                inst,
                "resolve",
                old_status=old_status,
                new_status=HrAlertInstance.Status.RESOLVED,
                at=now,
                by=context.user_id,
            )
            inst.save(
                update_fields=[
                    "status",
                    "resolved_at",
                    "resolved_reason",
                    "last_seen_at",
                    "payload_json",
                ]
            )
            count += 1
        return count

    def _reactivate_expired_snoozes(self, context: HrRequestContext) -> int:
        """snooze 窗口已过 → 恢复 OPEN（幂等，仅在读入口顺带执行）。"""
        now = context.now()
        qs = HrAlertInstance.objects.filter(
            tenant_id=context.tenant_id, status=HrAlertInstance.Status.SNOOZED
        )
        count = 0
        for inst in qs:
            if self._snooze_expired(inst, now):
                old_status = inst.status
                inst.status = HrAlertInstance.Status.OPEN
                self._append_audit(
                    inst,
                    "snooze_expired",
                    old_status=old_status,
                    new_status=HrAlertInstance.Status.OPEN,
                    at=now,
                    by=context.user_id,
                )
                inst.save(update_fields=["status", "payload_json"])
                count += 1
        return count

    @staticmethod
    def _snooze_expired(inst: HrAlertInstance, now: datetime) -> bool:
        snooze = (inst.payload_json or {}).get("snooze")
        if not snooze:
            return True  # SNOOZED 却无 snooze 元数据 → 视为已过期
        raw = snooze.get("until")
        if not raw:
            return True
        until = parse_datetime(raw)
        return until is None or until <= now

    @staticmethod
    def _parse_until(until, context: HrRequestContext) -> datetime:
        """解析 snooze 截止：datetime/date/ISO 字符串 → 学校时区 aware datetime。"""
        if isinstance(until, datetime):
            dt = until
        elif isinstance(until, date):
            dt = datetime.combine(until, time(23, 59, 59))
        elif isinstance(until, str):
            parsed = parse_datetime(until)
            if parsed is None:
                parsed = parse_date(until)
            if parsed is None:
                raise AlertServiceError("INVALID_UNTIL", "无效的 snooze 截止时间")
            dt = parsed
            if not isinstance(parsed, datetime):
                dt = datetime.combine(parsed, time(23, 59, 59))
        else:
            raise AlertServiceError("INVALID_UNTIL", "无效的 snooze 截止时间")

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=context.tzinfo())
        return dt

    @staticmethod
    def _append_audit(
        inst: HrAlertInstance,
        action: str,
        *,
        old_status: str,
        new_status: str,
        at: datetime,
        by=None,
        reason: str = "",
    ):
        payload = dict(inst.payload_json or {})
        trail = list(payload.get("audit") or [])
        trail.append(
            {
                "action": action,
                "from": old_status,
                "to": new_status,
                "at": at.isoformat(),
                "by": by,
                "reason": reason,
            }
        )
        payload["audit"] = trail
        inst.payload_json = payload

    @staticmethod
    def _dto(inst: HrAlertInstance) -> dict:
        return AlertSelector._to_dto(inst, inst.last_seen_at or inst.first_seen_at)
