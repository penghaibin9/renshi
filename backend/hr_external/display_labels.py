"""
hr_external/display_labels.py —— 展示层中文标签映射（前端中文化 + JSON label 规范）。

机器字段名保持 camelCase（status/genderCode/poolStatus...）；人看的中文用成对字段
（statusLabel/genderLabel/poolStatusLabel...）提供。本模块是单一来源，供 API 序列化
与模板共用，避免散落魔法字符串。

数据库枚举值（ACTIVE 等）不改，只映射展示文案。
"""

from __future__ import annotations

# Engagement 状态 → 中文（与 models/engagement 状态机一致）
ENGAGEMENT_STATUS_LABELS = {
    "DRAFT": "草稿",
    "UNDER_REVIEW": "待审核",
    "APPROVED": "已批准",
    "WAITING_AGREEMENT": "待签署协议",
    "SIGNED_WAITING_EFFECTIVE": "已签署待生效",
    "ACTIVE": "聘期中",
    "REVIEW_DUE": "待续聘评估",
    "RENEWAL_IN_PROGRESS": "续聘中",
    "EXPIRED": "已到期",
    "EXITING": "退出中",
    "ENDED": "已结束",
    "ARCHIVED": "已归档",
    "RETURNED": "已退回",
    "REJECTED": "已拒绝",
    "CANCELLED": "已取消",
    "SUSPENDED": "已暂停",
    "BLOCKED": "已阻断",
}

# 外聘类别 → 中文（enum 显示名）
CATEGORY_LABELS = {
    "PART_TIME_TEACHER": "兼职教师",
    "EXTERNAL_TEACHER": "外聘教师",
    "INDUSTRY_ADJUNCT": "产业兼职教师",
    "INDUSTRY_PROFESSOR": "产业教授",
    "SKILL_MASTER": "技能大师",
    "INDUSTRY_MENTOR": "产业导师",
    "VISITING_PROFESSOR": "客座教授",
    "GUEST_PROFESSOR": "讲座教授",
    "HONORARY_TITLE": "荣誉/名誉称号",
    "EXTERNAL_EXPERT": "外聘专家",
    "PRACTICE_INSTRUCTOR": "实践教学指导教师",
    "RETIRED_REHIRE_EXTERNAL": "退休返聘（外聘）",
    "PROJECT_EXPERT": "项目专家",
    "OTHER": "其他",
}

# 候选池状态 → 中文
POOL_STATUS_LABELS = {
    "AVAILABLE": "可聘",
    "UNDER_REVIEW": "待核验",
    "ENGAGED": "受聘中",
    "TEMPORARILY_UNAVAILABLE": "暂停合作",
    "DO_NOT_ENGAGE": "受限",
    "ARCHIVED": "已归档",
}

# 伦理状态 → 中文
ETHICS_STATUS_LABELS = {
    "NONE": "未要求",
    "PENDING": "待审查",
    "PASS": "通过",
    "NEEDS_REVIEW": "需复核",
    "FAIL": "未通过",
    "EXPIRED": "已过期",
}

# 身份核验状态 → 中文
IDENTITY_VERIFICATION_LABELS = {
    "UNVERIFIED": "未核验",
    "PENDING": "待核验",
    "VERIFIED": "已核验",
    "REJECTED": "已拒绝",
    "EXPIRED": "已过期",
}

# 任务状态 → 中文
TASK_STATUS_LABELS = {
    "DRAFT": "草稿",
    "ASSIGNED": "已分配",
    "ACCEPTED": "已接受",
    "IN_PROGRESS": "进行中",
    "SUBMITTED": "已提交",
    "UNDER_REVIEW": "验收中",
    "COMPLETED": "已完成",
    "REJECTED_FOR_CORRECTION": "退回修改",
    "CANCELLED": "已取消",
}

# 任务接受状态 → 中文
TASK_ACCEPTANCE_LABELS = {
    "PENDING": "待确认",
    "ACCEPTED": "已接受",
    "REQUEST_CLARIFICATION": "申请澄清",
    "DECLINED_WITH_REASON": "已婉拒",
}

# 工作量验证状态 → 中文
WORKLOAD_VERIFICATION_LABELS = {
    "UNVERIFIED": "未核验",
    "PENDING": "待核验",
    "VERIFIED": "已核验",
    "REJECTED": "已拒绝",
}

# 结算状态 → 中文
SETTLEMENT_STATUS_LABELS = {
    "NOT_ELIGIBLE": "不适用",
    "PENDING": "待结算",
    "READY": "已就绪",
    "VERIFIED": "已核验",
    "LOCKED": "已锁定",
}

# 成果核验状态 → 中文
CONTRIBUTION_VERIFICATION_LABELS = {
    "UPLOADED": "已上传",
    "PENDING_VERIFICATION": "待核验",
    "VERIFIED": "已核验",
    "REJECTED": "已拒绝",
}

# 退出原因 → 中文
EXIT_REASON_LABELS = {
    "TERM_COMPLETED": "聘期届满",
    "NO_RENEWAL": "不予续聘",
    "PERSON_WITHDRAWAL": "本人退出",
    "SCHOOL_TERMINATION": "学校终止",
    "TASK_COMPLETED": "任务完成",
    "ROLE_CONVERTED": "角色转换",
    "REGULAR_HIRE": "转为正式",
    "COMPLIANCE_REASON": "合规原因",
    "OTHER": "其他",
}

# 退出状态 → 中文
EXIT_STATUS_LABELS = {
    "PLANNED": "已计划",
    "UNDER_REVIEW": "待审核",
    "READY_TO_EXIT": "待退出",
    "EXITING": "退出中",
    "ENDED": "已结束",
    "CLEARANCE_PENDING": "待清结",
    "CLOSED": "已关闭",
}

# 续聘评审状态 → 中文
RENEWAL_STATUS_LABELS = {
    "DRAFT": "草稿",
    "IN_REVIEW": "评审中",
    "DECIDED": "已决策",
    "CANCELLED": "已取消",
}

# 协议状态（HR07 Provider 投影）→ 中文
AGREEMENT_STATUS_LABELS = {
    "UNAVAILABLE": "协议未接入",
    "NOT_REQUIRED": "无需协议",
    "DRAFT": "协议草稿",
    "UNDER_APPROVAL": "协议审批中",
    "WAITING_SIGNATURE": "待签署",
    "SIGNED": "已签署",
    "ACTIVE": "协议生效",
    "TERMINATED": "协议终止",
}

# 访问授权状态 → 中文
ACCESS_GRANT_STATUS_LABELS = {
    "PENDING": "待下发",
    "GRANTED": "已授权",
    "EXPIRED": "已过期",
    "REVOKED": "已回收",
    "FAILED_RETRYABLE": "失败可重试",
    "REVOKE_FAILED": "回收失败",
}

# 教务身份状态 → 中文
ACADEMIC_IDENTITY_LABELS = {
    "PENDING": "待开通",
    "ACTIVE": "有效",
    "SUSPENDED": "已暂停",
    "EXPIRED": "已过期",
    "REVOKED": "已停用",
}

# 材料状态 → 中文
MATERIAL_STATUS_LABELS = {
    "UPLOADED": "已上传",
    "VERIFIED": "已核验",
    "REJECTED": "已拒绝",
    "SUPERSEDED": "已替代",
}

# 导入任务状态 → 中文
IMPORT_JOB_STATUS_LABELS = {
    "UPLOADED": "已上传",
    "VALIDATING": "校验中",
    "VALIDATION_FAILED": "校验失败",
    "READY_TO_COMMIT": "待确认",
    "COMMITTING": "提交中",
    "COMPLETED": "已完成",
    "PARTIAL_FAILED": "部分失败",
    "FAILED": "失败",
}

# 材料类别 → 中文
MATERIAL_CATEGORY_LABELS = {
    "IDENTITY": "身份证明",
    "EDUCATION": "学历",
    "DEGREE": "学位",
    "PROFESSIONAL_TITLE": "职称",
    "SKILL_CERTIFICATE": "技能证书",
    "ENTERPRISE_EXPERIENCE": "企业经历",
    "AGREEMENT": "协议",
    "CONTRIBUTION_EVIDENCE": "成果证据",
    "OTHER": "其他",
}

# 性别 → 中文
GENDER_LABELS = {
    "M": "男",
    "F": "女",
    "O": "其他",
    "U": "未填写",
}

# 数据范围 → 中文
SCOPE_LABELS = {
    "SCHOOL": "全校",
    "COLLEGE": "学院",
    "ORGANIZATION": "组织",
    "ENGAGEMENT": "本聘期",
    "ASSIGNED_TASKS": "本人任务",
    "SELF": "仅本人",
}


def _label(mapping: dict, value) -> str:
    """取 label；未知值回退显示原值（不伪造中文）。"""
    if value is None:
        return ""
    return mapping.get(value, str(value))


def engagement_status_label(status) -> str:
    return _label(ENGAGEMENT_STATUS_LABELS, status)


def category_label(code) -> str:
    return _label(CATEGORY_LABELS, code)


def pool_status_label(status) -> str:
    return _label(POOL_STATUS_LABELS, status)


def ethics_status_label(status) -> str:
    return _label(ETHICS_STATUS_LABELS, status)


def identity_verification_label(status) -> str:
    return _label(IDENTITY_VERIFICATION_LABELS, status)


def task_status_label(status) -> str:
    return _label(TASK_STATUS_LABELS, status)


def task_acceptance_label(status) -> str:
    return _label(TASK_ACCEPTANCE_LABELS, status)


def workload_verification_label(status) -> str:
    return _label(WORKLOAD_VERIFICATION_LABELS, status)


def settlement_status_label(status) -> str:
    return _label(SETTLEMENT_STATUS_LABELS, status)


def contribution_verification_label(status) -> str:
    return _label(CONTRIBUTION_VERIFICATION_LABELS, status)


def exit_reason_label(reason) -> str:
    return _label(EXIT_REASON_LABELS, reason)


def exit_status_label(status) -> str:
    return _label(EXIT_STATUS_LABELS, status)


def renewal_status_label(status) -> str:
    return _label(RENEWAL_STATUS_LABELS, status)


def agreement_status_label(status) -> str:
    return _label(AGREEMENT_STATUS_LABELS, status)


def access_grant_status_label(status) -> str:
    return _label(ACCESS_GRANT_STATUS_LABELS, status)


def academic_identity_label(status) -> str:
    return _label(ACADEMIC_IDENTITY_LABELS, status)


def material_status_label(status) -> str:
    return _label(MATERIAL_STATUS_LABELS, status)


def import_job_status_label(status) -> str:
    return _label(IMPORT_JOB_STATUS_LABELS, status)


def material_category_label(code) -> str:
    return _label(MATERIAL_CATEGORY_LABELS, code)


def gender_label(code) -> str:
    return _label(GENDER_LABELS, code)


def scope_label(code) -> str:
    return _label(SCOPE_LABELS, code)
