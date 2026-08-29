"""HR07 合同管理 Authority 边界与恢复状态。"""

MODULE_CODE = "HR07"
MODULE_NAME = "合同管理"
TARGET_APP_LABEL = "hr_contracts"
CANONICAL_API_ROOT = "/api/v1/hr"
RECOVERY_STATE = "CANONICAL_AGREEMENT_ACTIVE"
SAFE_TO_REGISTER = True

OWNS = (
    "合同主档与版本",
    "签订、续签、变更、解除等合同案例",
    "合同有效期与生效历史",
)
EXPECTED_PRODUCTION_GUARDS = (
    "tenant fail-closed",
    "canonical permission hr.contracts.*",
    "幂等命令",
    "有效期历史 [effective_from, effective_to)",
    "FINAL/EFFECTIVE/CLOSED 不可变",
    "与 HR03/HR05/HR06 通过命令或注册业务事件交接",
)
RECOVERED_CORE_PARTS = (
    "Django AppConfig",
    "Authority models",
    "0001 migration 历史",
    "AgreementService 首签/生效写边界",
    "续签/变更/解除正式版本追加写链",
    "/api/v1/hr/contracts/agreements Canonical API",
    "/api/v1/hr/contracts/cases Canonical API",
    "Canonical Permission/Event definitions",
    "共享 durable event/outbox 投递",
    "Authority UI 正式入口",
)
REMAINING_CORE_PARTS = (
    "模板与规则 Authority",
    "到期预警与风险处置 Authority",
)
