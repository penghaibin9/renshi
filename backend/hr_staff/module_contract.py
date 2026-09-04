"""HR03 教职工主档模块边界合同。"""

MODULE_CODE = "HR03"
MODULE_NAME = "教职工主档"
APP_LABEL = "hr_staff"
CANONICAL_API_ROOT = "/api/v1/hr"
LEGACY_API_ROOTS = ("/api/hr/v1",)

OWNS = (
    "教职工身份主档",
    "教职工基础信息及受控更正历史",
    "人员主标识与在校人事身份事实",
    "PersonnelDecision 不可变正式人事决定事实",
    "奖惩/处分 Case → EFFECTIVE PersonnelDecision 正式事实链",
)
FORBIDDEN_DIRECT_WRITES = (
    "组织岗位结构",
    "招聘过程事实",
    "合同与异动历史",
    "考勤考核事实",
)

BUSINESS_EVENT_PRODUCER = True
BUSINESS_EVENT_POLICY = "TRANSACTIONAL_OUTBOX"

MATERIAL_SECURITY_POLICY = (
    "private tenant/staff-partitioned storage",
    "malware + size + extension + MIME + magic-byte validation",
    "actor-bound one-time ticket transported only in request headers",
    "audit succeeds before file streaming",
)
