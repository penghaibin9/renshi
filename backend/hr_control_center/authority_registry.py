"""HR01 canonical permission registration and read-model event policy."""

from horilla.hr_permission_registry import PermissionDefinition, register_permissions

from hr_control_center.permissions import HR_DASHBOARD_PERMISSIONS


_PERMISSION_DESCRIPTIONS = {
    "hr.dashboard.view": "访问人事工作台",
    "hr.dashboard.overview.view": "查看工作台总览",
    "hr.dashboard.todo.view": "查看本人及授权范围待办",
    "hr.dashboard.todo.supervise": "督办授权范围待办",
    "hr.dashboard.alert.view": "查看授权范围人事预警",
    "hr.dashboard.alert.manage": "确认、延后及关闭人事预警",
    "hr.dashboard.workforce.view": "查看队伍结构汇总",
    "hr.dashboard.workforce.drilldown": "下钻队伍结构明细",
    "hr.dashboard.quick_action.use": "使用工作台快捷办理入口",
    "hr.dashboard.export": "导出工作台授权数据",
    "hr.dashboard.sensitive_metrics.view": "查看工作台敏感指标",
}

PERMISSION_DEFINITIONS = tuple(
    PermissionDefinition(code, "HR01", _PERMISSION_DESCRIPTIONS[code])
    for code in HR_DASHBOARD_PERMISSIONS
)
register_permissions(PERMISSION_DEFINITIONS)

# HR01 is a read-model/aggregation Authority. It consumes other domains but does
# not publish cross-domain business facts. Alert acknowledgement and dashboard
# preferences remain local UI state and deliberately are not business events.
PRODUCES_BUSINESS_EVENTS = False
EVENT_DEFINITIONS = ()
