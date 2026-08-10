"""HR04 招聘模块边界合同。"""

MODULE_CODE = "HR04"
MODULE_NAME = "招聘管理"
APP_LABEL = "hr_recruitment"
CANONICAL_API_ROOT = "/api/v1/hr"
LEGACY_API_ROOTS = ("/api/hr/v1",)

OWNS = (
    "招聘需求与岗位招聘计划",
    "候选人及招聘过程事实",
    "招聘评审与录用决策事实",
)
FORBIDDEN_DIRECT_WRITES = (
    "正式教职工主档",
    "正式入职事实",
    "合同事实",
)
HANDOFF_TARGETS = (
    "HR05 入职：录用完成后通过正式交接命令进入入职流程",
)
