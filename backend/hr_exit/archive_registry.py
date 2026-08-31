"""HR16 archive-transfer permission and event definitions."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events
from horilla.hr_permission_registry import PermissionDefinition, register_permissions

PERM_ARCHIVE_VIEW = "hr.exit.archive_transfer.view"
PERM_ARCHIVE_MANAGE = "hr.exit.archive_transfer.manage"

PERM_EXIT_VIEW = "hr.exit.view"
PERM_EXIT_MANAGE = "hr.exit.manage"
PERM_EXIT_HANDOVER = "hr.exit.handover"
PERM_EXIT_EFFECT = "hr.exit.effect"
PERM_EXIT_FACT_CORRECT = "hr.exit.fact.correct"
PERM_EXIT_FACT_REVOKE = "hr.exit.fact.revoke"
PERM_RETIREMENT_POLICY_MANAGE = "hr.exit.retirement_policy.manage"
PERM_RETIREMENT_PRECHECK = "hr.exit.retirement_precheck.execute"
PERM_RETIREMENT_PENSION_MANAGE = "hr.exit.retirement.pension.manage"

register_permissions(
    (
        PermissionDefinition(PERM_ARCHIVE_VIEW, "HR16", "查看档案转递及签收凭证"),
        PermissionDefinition(PERM_ARCHIVE_MANAGE, "HR16", "办理档案转递、签收、退回与更正"),
        PermissionDefinition(PERM_EXIT_VIEW, "HR16", "查看退休与离校案件及正式事实"),
        PermissionDefinition(PERM_EXIT_MANAGE, "HR16", "办理退休与离校正式流程"),
        PermissionDefinition(PERM_EXIT_HANDOVER, "HR16", "维护离校交接清单与证据"),
        PermissionDefinition(PERM_EXIT_EFFECT, "HR16", "执行离校跨域正式生效"),
        PermissionDefinition(
            PERM_EXIT_FACT_CORRECT,
            "HR16",
            "以新版本更正已封板离校正式事实",
        ),
        PermissionDefinition(
            PERM_EXIT_FACT_REVOKE,
            "HR16",
            "以撤销版本终止已封板离校正式事实",
        ),
        PermissionDefinition(
            PERM_RETIREMENT_POLICY_MANAGE,
            "HR16",
            "维护并激活版本化退休政策",
        ),
        PermissionDefinition(
            PERM_RETIREMENT_PRECHECK,
            "HR16",
            "执行可解释退休日期预审",
        ),
        PermissionDefinition(
            PERM_RETIREMENT_PENSION_MANAGE,
            "HR16",
            "推进退休养老金办理进度并提交证据",
        ),
    )
)

EVENT_ARCHIVE_SENT = "hr.exit.archive_transfer.sent"
EVENT_ARCHIVE_RECEIVED = "hr.exit.archive_transfer.received"
EVENT_ARCHIVE_RETURNED = "hr.exit.archive_transfer.returned"
EVENT_CASE_APPROVED = "hr.exit.exit_case.approved"
EVENT_EXIT_FACT_EFFECTIVE = "hr.exit.exit_fact.effective"
EVENT_EXIT_FACT_REVISED = "hr.exit.exit_fact.revised"
EVENT_EXIT_FACT_REVOKED = "hr.exit.exit_fact.revoked"
EVENT_RETIREMENT_FACT_EFFECTIVE = "hr.exit.retirement_fact.effective"
EVENT_RETIREMENT_FACT_REVISED = "hr.exit.retirement_fact.revised"
EVENT_RETIREMENT_FACT_REVOKED = "hr.exit.retirement_fact.revoked"
EVENT_RETIREMENT_POLICY_ACTIVATED = "hr.exit.retirement_policy.activated"
EVENT_RETIREMENT_PRECHECK_COMPLETED = "hr.exit.retirement_precheck.completed"
EVENT_RETIREMENT_PENSION_STATUS_CHANGED = "hr.exit.retirement.pension_status_changed"

register_business_events(
    (
        BusinessEventDefinition(EVENT_ARCHIVE_SENT, "HR16", "archive_transfer", 1),
        BusinessEventDefinition(EVENT_ARCHIVE_RECEIVED, "HR16", "archive_transfer", 1),
        BusinessEventDefinition(EVENT_ARCHIVE_RETURNED, "HR16", "archive_transfer", 1),
        BusinessEventDefinition(EVENT_CASE_APPROVED, "HR16", "exit_case", 1),
        BusinessEventDefinition(EVENT_EXIT_FACT_EFFECTIVE, "HR16", "exit_fact", 1),
        BusinessEventDefinition(EVENT_EXIT_FACT_REVISED, "HR16", "exit_fact", 1),
        BusinessEventDefinition(EVENT_EXIT_FACT_REVOKED, "HR16", "exit_fact", 1),
        BusinessEventDefinition(
            EVENT_RETIREMENT_FACT_EFFECTIVE,
            "HR16",
            "retirement_fact",
            1,
        ),
        BusinessEventDefinition(
            EVENT_RETIREMENT_POLICY_ACTIVATED,
            "HR16",
            "retirement_policy",
            1,
        ),
        BusinessEventDefinition(
            EVENT_RETIREMENT_PRECHECK_COMPLETED,
            "HR16",
            "retirement_precheck",
            1,
        ),
        BusinessEventDefinition(EVENT_RETIREMENT_FACT_REVISED, "HR16", "retirement_fact", 1),
        BusinessEventDefinition(EVENT_RETIREMENT_FACT_REVOKED, "HR16", "retirement_fact", 1),
        BusinessEventDefinition(
            EVENT_RETIREMENT_PENSION_STATUS_CHANGED,
            "HR16",
            "retirement",
            1,
        ),
    )
)
