"""
hr_onboarding/api/labels.py

JSON 字段规范（总控 §12 / 台账 §12）：机器字段名 camelCase 不改，中文用成对 label。
- {status:"ACTIVE", statusLabel:"在职"}；
- 枚举值零改动，仅展示层映射；
- 本模块集中维护 HR05 枚举 → 中文 label，避免散落各处。
"""

from __future__ import annotations

from django.utils.translation import gettext as _

# Case 状态 → 中文
CASE_STATUS_LABELS = {
    "CREATED": _("已创建"),
    "PREPARING": _("准备中"),
    "READY_TO_REPORT": _("可报到"),
    "REPORT_SCHEDULED": _("已预约报到"),
    "REPORTED": _("已报到"),
    "VERIFYING": _("材料核验中"),
    "READY_FOR_ACTIVATION": _("待正式生效"),
    "ACTIVATING": _("正式生效中"),
    "ACTIVE": _("已生效"),
    "ONBOARDING_IN_PROGRESS": _("入职协同中"),
    "ONBOARDING_COMPLETED": _("入职完成"),
    "PROBATION": _("试用期"),
    "CONFIRMED": _("已转正"),
    "REPORT_DELAYED": _("报到延期"),
    "DECLINED": _("已放弃"),
    "NO_SHOW": _("未报到"),
    "BLOCKED": _("已阻断"),
    "ACTIVATION_FAILED": _("生效失败"),
    "CANCELLED": _("已取消"),
    "PROBATION_EXTENDED": _("试用期延长"),
    "PROBATION_FAILED": _("试用不合格"),
}

# 来源类型 → 中文
SOURCE_TYPE_LABELS = {
    "HR04_HIRE": _("招聘录用"),
    "LEGAL_MANUAL_MIGRATION": _("合法人工迁移"),
    "TRANSFER_IN": _("调入"),
    "POLICY_IMPORT": _("政策导入"),
    "LEGACY_MIGRATION": _("历史数据迁移"),
}

# 用工类型 → 中文
EMPLOYMENT_TYPE_LABELS = {
    "FULL_TIME": _("全职"),
    "PART_TIME": _("兼职"),
    "EXTERNAL": _("外聘"),
    "RETIRED_REHIRED": _("退休返聘"),
    "OTHER": _("其他"),
}

# 人员类别 → 中文
STAFF_CATEGORY_LABELS = {
    "TEACHER": _("专任教师"),
    "ADMIN": _("行政管理"),
    "ENGINEERING_TECHNICAL": _("其他专技"),
    "EXPERIMENTAL": _("实验实训"),
    "LIBRARY_ARCHIVES": _("图书档案"),
    "LOGISTICS": _("工勤"),
    "OTHER": _("其他"),
}

# Person 匹配 → 中文
PERSON_MATCH_LABELS = {
    "EXACT_MATCH": _("精确匹配"),
    "POSSIBLE_MATCH": _("疑似匹配"),
    "NO_MATCH": _("无匹配"),
    "INSUFFICIENT_DATA": _("信息不足"),
}

# 激活状态 → 中文
ACTIVATION_STATUS_LABELS = {
    "NOT_STARTED": _("未开始"),
    "IN_PROGRESS": _("进行中"),
    "SUCCEEDED": _("已成功"),
    "PARTIAL_FAILED": _("部分失败"),
    "FAILED": _("已失败"),
}

# 核验状态 → 中文
VERIFICATION_STATUS_LABELS = {
    "UNVERIFIED": _("未核验"),
    "PENDING": _("待核验"),
    "VERIFIED": _("已核验"),
    "REJECTED": _("已拒绝"),
    "EXPIRED": _("已过期"),
}

# 材料状态 → 中文
MATERIAL_STATUS_LABELS = {
    "MISSING": _("缺失"),
    "SUBMITTED": _("已提交"),
    "UNDER_REVIEW": _("核验中"),
    "RETURNED": _("已退回"),
    "VERIFIED": _("已核验"),
    "REJECTED": _("已拒绝"),
    "EXPIRED": _("已过期"),
    "WAIVED": _("已豁免"),
}

# 材料阻断阶段 → 中文
BLOCKING_PHASE_LABELS = {
    "PRE_REPORT": _("报到前"),
    "REPORT": _("报到时"),
    "ACTIVATION": _("生效前"),
    "POST_ACTIVATION": _("生效后"),
    "PROBATION": _("试用期"),
}

# 材料复用策略 → 中文
REUSE_POLICY_LABELS = {
    "TRUST_SOURCE": _("信任来源"),
    "REVERIFY": _("需复核"),
    "REQUIRE_ORIGINAL": _("需原件"),
}

# 任务状态 → 中文
TASK_STATUS_LABELS = {
    "NOT_STARTED": _("未开始"),
    "READY": _("就绪"),
    "IN_PROGRESS": _("进行中"),
    "WAITING_EXTERNAL": _("等待外部"),
    "BLOCKED": _("已阻塞"),
    "COMPLETED": _("已完成"),
    "WAIVED": _("已豁免"),
    "FAILED": _("已失败"),
    "CANCELLED": _("已取消"),
}

# 阻断等级 → 中文
BLOCKING_LEVEL_LABELS = {
    "INFO": _("提示"),
    "NON_BLOCKING": _("不阻断"),
    "BLOCKS_ACTIVATION": _("阻断生效"),
    "BLOCKS_ONBOARDING_COMPLETE": _("阻断入职完成"),
    "BLOCKS_PAYROLL": _("阻断薪酬"),
    "BLOCKS_WORK_ACCESS": _("阻断工作访问"),
}

# 责任人角色 → 中文
RESPONSIBLE_ROLE_LABELS = {
    "RESPONSIBLE_HR": _("人事负责人"),
    "COLLEGE_HR": _("学院人事"),
    "HIRING_MANAGER": _("用人部门"),
    "IT_SERVICE": _("信息技术"),
    "FINANCE_SERVICE": _("财务"),
    "ACADEMIC_SERVICE": _("教务"),
    "CUSTOM_GROUP": _("自定义组"),
}

# Provisioning 状态 → 中文
PROVISIONING_STATUS_LABELS = {
    "PENDING": _("待处理"),
    "RUNNING": _("执行中"),
    "SUCCESS": _("成功"),
    "FAILED_RETRYABLE": _("失败待重试"),
    "FAILED_TERMINAL": _("失败终态"),
    "CANCELLED": _("已取消"),
}

# 试用状态 → 中文
PROBATION_STATUS_LABELS = {
    "NOT_STARTED": _("未开始"),
    "IN_PROGRESS": _("进行中"),
    "REVIEW_DUE": _("待评价"),
    "UNDER_REVIEW": _("评价中"),
    "EXTENDED": _("已延长"),
    "CONFIRMED": _("已转正"),
    "FAILED": _("不合格"),
    "CANCELLED": _("已取消"),
}

# 试用结果 → 中文
PROBATION_RESULT_LABELS = {
    "NONE": _("未定"),
    "CONFIRMED": _("已转正"),
    "EXTENDED": _("已延长"),
    "FAILED": _("不合格"),
}


def label_for(mapping: dict, value: str | None) -> str:
    """从映射取中文 label；未知/空返回原值。"""
    if not value:
        return ""
    return mapping.get(value, value)
