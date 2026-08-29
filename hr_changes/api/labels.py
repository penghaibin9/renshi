"""
hr_changes/api/labels.py —— HR06 枚举 → 中文 label 统一映射（总控 JSON 字段规范）。

契约：
- 机器字段名不变（camelCase）；人看的中文用成对字段 {status:"ACTIVE", statusLabel:"生效中"}。
- 数据库枚举值不改；只做展示层映射。
- 全系统统一在此维护，禁止各 API 散写 label 映射。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 状态/枚举 → 中文 label（V1 冻结）
# ---------------------------------------------------------------------------
CASE_STATUS_LABELS = {
    "DRAFT": "草稿",
    "VALIDATING": "校验中",
    "READY_TO_SUBMIT": "待提交",
    "SUBMITTED": "已提交",
    "UNDER_APPROVAL": "审批中",
    "RETURNED": "已退回",
    "RESUBMITTED": "已重新提交",
    "APPROVED_WAITING_EFFECTIVE": "已批准待生效",
    "APPLYING": "生效中",
    "EFFECTIVE": "已生效",
    "CLOSED": "已关闭",
    "REJECTED": "已驳回",
    "WITHDRAWN": "已撤回",
    "CANCELLED": "已取消",
    "APPLY_FAILED": "生效失败",
    "RESCINDED": "已撤销",
    "CORRECTED": "已更正",
}

ACTION_LABELS = {
    "ORG_TRANSFER": "组织调动",
    "POSITION_TRANSFER": "岗位调动",
    "ORG_POSITION_TRANSFER": "组织+岗位调动",
    "POST_CATEGORY_CHANGE": "岗位类别变更",
    "EMPLOYEE_CATEGORY_CHANGE": "人员类别变更",
    "EMPLOYMENT_TYPE_CHANGE": "用工性质变更",
    "MANAGER_CHANGE": "直属上级变更",
    "LOCATION_CHANGE": "工作地点变更",
    "ADD_SECONDARY_ASSIGNMENT": "增加兼岗",
    "END_SECONDARY_ASSIGNMENT": "取消兼岗",
    "PRIMARY_ASSIGNMENT_SWITCH": "主岗切换",
    "TEMPORARY_SECONDMENT": "借调",
    "TEMPORARY_ATTACHMENT": "挂职",
    "RETURN_FROM_TEMPORARY": "返岗",
    "BULK_ORG_RESTRUCTURE_MOVE": "批量组织调整",
    "DATA_CORRECTION": "数据纠错",
}

IMPACT_LEVEL_LABELS = {
    "BLOCKER": "阻断",
    "WARNING": "业务影响",
    "INFO": "提示",
}

PRIORITY_LABELS = {
    "LOW": "低",
    "NORMAL": "普通",
    "HIGH": "高",
    "URGENT": "紧急",
}

SCOPE_LABELS = {
    "SCHOOL": "全校",
    "COLLEGE": "学院",
    "ORGANIZATION": "组织",
    "SELF": "本人",
    "ASSIGNED_CASES": "指派案件",
    "SOURCE_ORG": "原单位",
    "TARGET_ORG": "目标单位",
}

DOWNSTREAM_STATUS_LABELS = {
    "PENDING": "待处理",
    "RUNNING": "处理中",
    "SUCCESS": "成功",
    "FAILED_RETRYABLE": "失败（可重试）",
    "FAILED_TERMINAL": "失败（终局）",
    "NOT_REQUIRED": "无需处理",
}

FUTURE_CONFLICT_LABELS = {
    "NO_CONFLICT": "无冲突",
    "REBASE_REQUIRED": "需重新对齐",
    "HARD_CONFLICT": "硬冲突",
}

SOURCE_ASSIGNMENT_POLICY_LABELS = {
    "KEEP_ACTIVE": "保持原岗",
    "SUSPEND": "原岗挂起",
    "REDUCE_FTE": "减少工作量",
}

REPORTING_MANAGER_POLICY_LABELS = {
    "KEEP": "保持原上级",
    "DERIVE_FROM_TARGET_ORG": "按目标单位推导",
    "SELECT_EXPLICIT": "显式选择",
}

EMPLOYMENT_TYPE_CHANGE_POLICY_LABELS = {
    "UPDATE_RELATIONSHIP": "更新聘用关系",
    "CLOSE_AND_CREATE_RELATIONSHIP": "关闭并新建聘用关系",
    "REQUIRE_HR07_CONTRACT": "需 HR07 合同变更",
}

# HR03 Authority 枚举在 HR06 表单中的中文展示。机器值仍以 HR03 constants 为唯一合同。
STAFF_CATEGORY_LABELS = {
    "TEACHER": "教师",
    "ADMIN": "行政管理",
    "ENGINEERING_TECHNICAL": "工程技术",
    "EXPERIMENTAL": "实验技术",
    "LIBRARY_ARCHIVES": "图书档案",
    "LOGISTICS": "后勤",
    "OTHER": "其他",
}

RELATIONSHIP_TYPE_LABELS = {
    "REGULAR_EMPLOYMENT": "正式聘用",
    "CONTRACT": "合同制",
    "LABOR_DISPATCH": "劳务派遣",
    "EXTERNAL_PART_TIME": "外聘兼职",
    "SECONDMENT": "借调",
    "RETIRED_REHIRE": "退休返聘",
    "REHIRE": "再聘",
    "OTHER": "其他",
}

EMPLOYMENT_TYPE_LABELS = {
    "FULL_TIME": "全职",
    "PART_TIME": "兼职",
    "EXTERNAL": "外聘",
    "RETIRED_REHIRED": "退休返聘",
    "OTHER": "其他",
}

# 事件类型 → 中文（Outbox 日志/台账展示）
EVENT_TYPE_LABELS = {
    "PersonnelChangeApproved": "异动批准",
    "PersonnelChangeEffective": "异动生效",
    "PersonnelChangeCorrected": "异动更正",
    "PersonnelChangeRescinded": "异动撤销",
    "PersonnelChangeSubmitted": "异动提交",
    "PersonnelChangeReturned": "异动退回",
    "PersonnelChangeScheduled": "异动已排期",
    "PersonnelChangeApplyFailed": "异动生效失败",
    "AssignmentChanged": "任职变更",
    "OrganizationTransferred": "组织调动",
    "PositionChanged": "岗位变更",
    "StaffCategoryChanged": "人员类别变更",
    "SecondaryAssignmentAdded": "兼岗增加",
    "SecondaryAssignmentEnded": "兼岗结束",
    "TemporaryAssignmentStarted": "临时异动开始",
    "TemporaryAssignmentEnded": "临时异动结束",
    "TemporaryAssignmentReturnDue": "临时异动返岗到期",
    "TemporaryAssignmentOverdue": "临时异动超期",
    "ContractReviewRequired": "合同复核请求",
    "CompensationRecalculationRequested": "薪酬重算请求",
    "AttendanceRuleReevaluationRequested": "考勤规则重评请求",
}


def _lookup(mapping: dict, value) -> str:
    if value is None or value == "":
        return ""
    return mapping.get(value, str(value))


def case_status_label(value) -> str:
    return _lookup(CASE_STATUS_LABELS, value)


def action_label(value) -> str:
    return _lookup(ACTION_LABELS, value)


def impact_level_label(value) -> str:
    return _lookup(IMPACT_LEVEL_LABELS, value)


def priority_label(value) -> str:
    return _lookup(PRIORITY_LABELS, value)


def scope_label(value) -> str:
    return _lookup(SCOPE_LABELS, value)


def downstream_status_label(value) -> str:
    return _lookup(DOWNSTREAM_STATUS_LABELS, value)


def future_conflict_label(value) -> str:
    return _lookup(FUTURE_CONFLICT_LABELS, value)


def source_assignment_policy_label(value) -> str:
    return _lookup(SOURCE_ASSIGNMENT_POLICY_LABELS, value)


def reporting_manager_policy_label(value) -> str:
    return _lookup(REPORTING_MANAGER_POLICY_LABELS, value)


def employment_type_change_policy_label(value) -> str:
    return _lookup(EMPLOYMENT_TYPE_CHANGE_POLICY_LABELS, value)


def staff_category_label(value) -> str:
    return _lookup(STAFF_CATEGORY_LABELS, value)


def relationship_type_label(value) -> str:
    return _lookup(RELATIONSHIP_TYPE_LABELS, value)


def employment_type_label(value) -> str:
    return _lookup(EMPLOYMENT_TYPE_LABELS, value)


def event_type_label(value) -> str:
    return _lookup(EVENT_TYPE_LABELS, value)
