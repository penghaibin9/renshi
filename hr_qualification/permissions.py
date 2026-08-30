"""Canonical HR09 permission definitions registered for Authority gates."""

from horilla.hr_permission_registry import PermissionDefinition, register_permissions
from hr_qualification.constants import HR09_PERMISSIONS


_DESCRIPTIONS = {
    "credential.view": "查看本校教师资格与职业资格事实",
    "credential.create": "登记教师资格与职业资格",
    "credential.verify": "核验教师资格与职业资格证据",
    "credential.revoke": "暂停或撤销教师资格事实",
    "credential.sensitive_view": "查看资格证号等受限字段",
    "credential.export": "导出资格受控数据",
    "rule.view": "查看双师型规则版本",
    "rule.manage": "维护双师型规则草稿",
    "rule.publish": "发布双师型正式规则版本",
    "application.self": "本人发起和查看双师型申请",
    "application.view": "查看本校双师型申请",
    "application.formal_review": "执行双师型形式审查",
    "review.score": "提交双师型评审评分",
    "review.panel_manage": "管理双师型评审组",
    "review.finalize": "作出双师型最终决定",
    "recognition.view": "查看双师型正式认定",
    "recognition.manage": "维护双师型认定有效期",
    "recognition.recheck": "发起和处理双师型复核",
    "recognition.revoke": "撤销双师型正式认定",
    "risk.view": "查看资格与双师型风险",
    "risk.manage": "处置资格与双师型风险",
}

PERMISSION_DEFINITIONS = tuple(
    PermissionDefinition(
        key,
        "HR09",
        _DESCRIPTIONS[key.removeprefix("hr.qualification.")],
    )
    for key in HR09_PERMISSIONS
)
register_permissions(PERMISSION_DEFINITIONS)
