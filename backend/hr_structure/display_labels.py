"""
hr_structure/display_labels.py

HR02 + HR01 统一中文展示标签（总控 §12 JSON 字段规范）。

规则：
- 机器字段名 camelCase 不动（status、orgType、severity）；
- 人看的中文用成对字段：{status:"ACTIVE", statusLabel:"在岗"}；
- 数据库枚举值零改动；仅于 API 响应构造时追加 *Label 字段。
"""

# ---- HR02 组织相关 ----
ORG_TYPE = {
    "SCHOOL": "学校",
    "CAMPUS": "校区",
    "COLLEGE": "学院",
    "DEPARTMENT": "系部",
    "OFFICE": "科室/办公室",
    "DIVISION": "处室",
    "SECTION": "科室",
    "TEACHING_RESEARCH_UNIT": "教研室",
    "LAB_CENTER": "实验中心",
    "RESEARCH_INSTITUTE": "研究院所",
    "DIRECT_AFFILIATED_UNIT": "直属单位",
    "PARTY_COMMITTEE": "党委",
    "PARTY_GENERAL_BRANCH": "党总支",
    "PARTY_BRANCH": "党支部",
    "VIRTUAL_ORG": "虚拟组织",
    "TEMP_ORG": "临时组织",
    "OTHER": "其他",
}

ORG_VERSION_STATUS = {
    "DRAFT": "草稿",
    "APPROVED": "已批准",
    "EFFECTIVE": "生效中",
    "SUPERSEDED": "已替代",
    "REJECTED": "已驳回",
    "CANCELLED": "已取消",
}

# ---- HR02 组织关系 ----
ORG_RELATION_TYPE = {
    "ADMIN_PARENT": "行政上级",
    "PARTY_PARENT": "党组织上级",
    "TEACHING_PARENT": "教学上级",
    "PARTY_COVERS": "党组织覆盖",
    "ADMIN_MATCH": "行政对应",
    "TEACHING_BELONGS_TO": "教学归属",
    "BUSINESS_REPORTS_TO": "业务归口",
    "BUSINESS_MANAGED_BY": "业务管理",
    "SHARED_SERVICE_FOR": "共享服务",
    "TEMP_COORDINATION": "临时协调",
}

ORG_RELATION_STATUS = {
    "ACTIVE": "有效",
    "CLOSED": "已关闭",
}

# ---- HR02 编制方案 ----
STAFFING_PLAN_STATUS = {
    "DRAFT": "草稿",
    "UNDER_REVIEW": "审核中",
    "RETURNED": "退回",
    "REJECTED": "驳回",
    "APPROVED": "已批准",
    "EFFECTIVE": "生效中",
    "SUPERSEDED": "已替代",
    "CANCELLED": "已取消",
}

# ---- HR02 岗位目录 ----
POST_CATALOG_CATEGORY = {
    "MANAGEMENT": "管理岗位",
    "PROFESSIONAL_TECHNICAL": "专业技术岗位",
    "SKILLED_WORKER": "工勤技能岗位",
    "SPECIAL": "特设岗位",
}

POST_CATALOG_SUBCATEGORY = {
    "TEACHER": "教师岗",
    "ENGINEERING_TECHNICAL": "其他专技岗",
    "LABORATORY": "实验技术岗",
    "LIBRARY_ARCHIVES": "图书档案岗",
    "ACCOUNTING_AUDIT": "会计审计岗",
    "MEDICAL_HEALTH": "医疗卫生岗",
    "EDITORIAL_PUBLICATION": "编辑出版岗",
    "OTHER_PROFESSIONAL": "其他专技",
}

POST_CATALOG_CONTROL_MODE = {
    "POSITION_CONTROL": "逐岗控制",
    "POOL_CONTROL": "额度控制",
}

# ---- HR02 岗位预占/台账 ----
POSITION_LIFECYCLE_STATUS = {
    "DRAFT": "草稿",
    "PENDING_APPROVAL": "待批准",
    "ACTIVE": "在岗",
    "FROZEN": "冻结",
    "CLOSED": "已关闭",
    "CANCELLED": "已取消",
}

POSITION_OCCUPANCY_STATUS = {
    "VACANT": "空缺",
    "PARTIALLY_FILLED": "部分在岗",
    "FILLED": "已满编",
    "OVERFILLED": "超编",
}

POSITION_RESERVATION_STATUS = {
    "HELD": "预占中",
    "COMMITTED": "已提交",
    "RELEASED": "已释放",
    "EXPIRED": "已过期",
    "CANCELLED": "已取消",
}

# ---- HR02 变更 ----
CHANGE_TYPE = {
    "CREATE_ORG": "新建组织",
    "RENAME_ORG": "组织更名",
    "CHANGE_ORG_TYPE": "变更类型",
    "REPARENT_ORG": "调整上级",
    "MERGE_ORGS": "合并组织",
    "SPLIT_ORG": "拆分组织",
    "DEACTIVATE_ORG": "停用组织",
    "REACTIVATE_ORG": "重新启用",
    "CREATE_RELATION": "新建关系",
    "CHANGE_RELATION": "变更关系",
    "MOVE_POSITION": "岗位迁移",
    "CREATE_POSITION": "新建岗位",
    "CHANGE_POSITION": "变更岗位",
    "CLOSE_POSITION": "关闭岗位",
    "ADJUST_STAFFING_QUOTA": "调整编制",
    "ADJUST_POSITION_QUOTA": "调整岗位额度",
}

CHANGE_CASE_STATUS = {
    "DRAFT": "草稿",
    "SUBMITTED": "已提交",
    "UNDER_REVIEW": "审核中",
    "RETURNED": "退回",
    "REJECTED": "驳回",
    "APPROVED": "已批准",
    "SCHEDULED": "已排期",
    "EFFECTIVE": "已生效",
    "CANCELLED": "已取消",
    "FAILED_EFFECT": "生效失败",
}

# ---- 权威模式 ----
AUTHORITY_MODE = {
    "LEGACY_ONLY": "历史系统快照",
    "LEGACY_STRUCTURE_ONLY": "历史系统组织结构",
    "DUAL_READ_COMPARE": "双读对账",
    "AUTHORITY_ONLY": "仅正式数据",
    "HR02_AUTHORITY": "HR02 正式数据",
}

# ---- HR01 预警 ----
ALERT_SEVERITY = {
    "CRITICAL": "严重",
    "HIGH": "高",
    "MEDIUM": "中",
    "LOW": "低",
    "INFO": "提示",
}

ALERT_STATUS = {
    "OPEN": "待处理",
    "ACKNOWLEDGED": "已确认",
    "SNOOZED": "已暂缓",
    "RESOLVED": "已解决",
    "EXPIRED": "已过期",
}

ALERT_CATEGORY = {
    "contract": "合同到期",
    "retirement": "退休临近",
    "data_quality": "数据质量",
    "workflow": "流程异常",
    "qualification": "资格到期",
}

# ---- HR01 指标新鲜度 ----
METRIC_FRESHNESS = {
    "OK": "正常",
    "PARTIAL": "部分可用",
    "STALE": "可能过期",
    "UNAVAILABLE": "暂不可用",
    "ERROR": "计算失败",
}

# ---- HR01 数据范围 ----
SCOPE_TYPE = {
    "SCHOOL": "全校",
    "COLLEGE": "学院",
    "DEPARTMENT": "系部",
    "ASSIGNED": "本人经办",
}

# ---- HR01 数据基础 ----
DATA_BASIS = {
    "LEGACY_CURRENT_SNAPSHOT": "当前系统快照",
    "AUTHORITATIVE_EFFECTIVE_FACT": "权威有效事实",
}

# ---- HR01 待办 ----
TODO_SEVERITY = {
    "CRITICAL": "严重",
    "HIGH": "高",
    "MEDIUM": "中",
    "LOW": "低",
}

# ---- 通用性别 ----
GENDER = {
    "male": "男",
    "female": "女",
    "other": "其他",
}


def label_of(mapping: dict, key, default=""):
    """安全取 label；非空 key 且在映射中则返回对应中文，否则返回 default。"""
    if key is None:
        return default
    return mapping.get(str(key), default)


def append_labels(d: dict, *, mappings: list):
    """
    给 dict 自动追加 *Label 字段。
    
    mappings: [(field_name, label_mapping_dict), ...]
    例: append_labels(d, mappings=[("status", STATUS_LABELS), ("orgType", ORG_TYPE)])
       → 若 d["status"]="ACTIVE" 则追加 d["statusLabel"]="生效中"
    """
    for field_name, mapping in mappings:
        value = d.get(field_name)
        if value is not None:
            d[f"{field_name}Label"] = label_of(mapping, value)


def append_labels_deep(items: list, *, field_mappings: list):
    """
    给列表中每个 dict 自动追加 *Label 字段。
    field_mappings: [(field_name, label_mapping_dict), ...]
    """
    for item in items:
        append_labels(item, mappings=field_mappings)
