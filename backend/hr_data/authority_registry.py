"""Canonical HR18 governance/submission permissions and business events."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

PERMISSIONS = (
    PermissionDefinition("hr.data.view", "HR18", "查看人事数据中心"),
    PermissionDefinition("hr.data.define", "HR18", "维护人口、维度和指标定义"),
    PermissionDefinition("hr.data.asof", "HR18", "执行历史时点证据重建"),
    PermissionDefinition("hr.data.quality", "HR18", "执行数据质量治理"),
    PermissionDefinition("hr.data.submit", "HR18", "创建并提交正式报送"),
    PermissionDefinition("hr.data.approve", "HR18", "独立审批正式报送"),
    PermissionDefinition("hr.data.receipt", "HR18", "登记外部正式回执"),
    PermissionDefinition("hr.data.exchange", "HR18", "管理异步数据交换与对账"),
    PermissionDefinition("hr.data.metric.evaluate", "HR18", "执行通用指标表达式求值"),
    PermissionDefinition("hr.data.legacy.takeover", "HR18", "执行旧报表证据接管与写封锁"),
)
register_permissions(PERMISSIONS)

EVENTS = (
    BusinessEventDefinition(
        "hr.data.quality_run.completed", "HR18", "quality_run", 1
    ),
    BusinessEventDefinition(
        "hr.data.submission.queued", "HR18", "submission", 1
    ),
    BusinessEventDefinition(
        "hr.data.submission.submitted", "HR18", "submission", 1
    ),
    BusinessEventDefinition(
        "hr.data.submission.accepted", "HR18", "submission", 1
    ),
    BusinessEventDefinition(
        "hr.data.submission.rejected", "HR18", "submission", 1
    ),
    BusinessEventDefinition(
        "hr.data.submission.corrected", "HR18", "submission", 1
    ),
    BusinessEventDefinition(
        "hr.data.submission.dispatch_retry_scheduled", "HR18", "submission", 1
    ),
    BusinessEventDefinition(
        "hr.data.submission.dispatch_dead", "HR18", "submission", 1
    ),
    BusinessEventDefinition("hr.data.exchange.queued", "HR18", "exchange", 1),
    BusinessEventDefinition("hr.data.exchange.transmitted", "HR18", "exchange", 1),
    BusinessEventDefinition("hr.data.exchange.reconciled", "HR18", "exchange", 1),
    BusinessEventDefinition("hr.data.exchange.dead_lettered", "HR18", "exchange", 1),
    BusinessEventDefinition(
        "hr.data.metric_evaluation.completed", "HR18", "metric_evaluation", 1
    ),
    BusinessEventDefinition(
        "hr.data.legacy_report.inventoried", "HR18", "legacy_report", 1
    ),
    BusinessEventDefinition(
        "hr.data.legacy_report.reconciled", "HR18", "legacy_report", 1
    ),
    BusinessEventDefinition(
        "hr.data.legacy_report.cutover", "HR18", "legacy_report", 1
    ),
    BusinessEventDefinition(
        "hr.data.legacy_report.write_blocked", "HR18", "legacy_report", 1
    ),
)
register_business_events(EVENTS)
