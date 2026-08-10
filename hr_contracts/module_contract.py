"""HR07 合同管理恢复合同。

重要：当前目录不是完整 Django app。本文件只记录设计边界和恢复状态，
不能被用来宣称 HR07 已完成或已经可以注册到 INSTALLED_APPS。
"""

MODULE_CODE = "HR07"
MODULE_NAME = "合同管理"
TARGET_APP_LABEL = "hr_contracts"
CANONICAL_API_ROOT = "/api/v1/hr"
RECOVERY_STATE = "INCOMPLETE"
SAFE_TO_REGISTER = False

OWNS = (
    "合同主档与版本",
    "签订、续签、变更、解除等合同案例",
    "合同有效期与生效历史",
)
EXPECTED_PRODUCTION_GUARDS = (
    "tenant fail-closed",
    "幂等命令",
    "有效期历史 [effective_from, effective_to)",
    "FINAL/EFFECTIVE/CLOSED 不可变",
    "与 HR03/HR05/HR06 通过命令或事件交接",
)
MISSING_CORE_PARTS = (
    "Django AppConfig",
    "完整模型入口",
    "migration 历史",
    "模块测试入口",
)
