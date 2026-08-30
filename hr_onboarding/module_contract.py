"""HR05 入职办理模块边界合同。"""

MODULE_CODE = "HR05"
MODULE_NAME = "入职办理"
APP_LABEL = "hr_onboarding"
CANONICAL_API_ROOT = "/api/v1/hr"
LEGACY_API_ROOTS = ("/api/hr/v1",)
PERMISSION_PREFIX = "hr.onboarding"
AUTHORITY_KIND = "ONBOARDING_PROCESS_AUTHORITY"

OWNS = (
    "录用后入职案例与材料",
    "入职任务、核验和办理状态",
    "正式到岗前的人事接入过程事实",
)
FORBIDDEN_DIRECT_WRITES = (
    "HR03 教职工主档",
    "HR07 合同权威事实",
    "HR06 人事异动事实",
)
HANDOFF_TARGETS = (
    "HR03：通过受控命令形成/关联正式教职工主档",
    "HR07：通过受控命令进入合同签订",
)
