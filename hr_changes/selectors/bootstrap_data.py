"""
hr_changes/selectors/bootstrap_data.py —— HR06 bootstrap 数据（S1）。

提供：动作/原因/受管字段/状态元数据；全部按 tenant 隔离 + 中文 label 成对。
"""

from __future__ import annotations

from hr_changes.api.labels import (
    action_label,
    case_status_label,
    employment_type_change_policy_label,
    impact_level_label,
    priority_label,
    reporting_manager_policy_label,
    source_assignment_policy_label,
)
from hr_changes.constants import (
    CASE_ACTIVE_STATUSES,
    CASE_TERMINAL_STATUSES,
    CaseStatus,
    ChangePriority,
    ChangeScopeType,
    EmploymentTypeChangePolicy,
    ImpactLevel,
    ReportingManagerPolicy,
    SourceAssignmentPolicy,
)
from hr_changes.models import HrChangeAction, HrChangeFieldDefinition, HrChangeReason


class BootstrapDataSelector:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def actions(self) -> list[dict]:
        actions = (
            HrChangeAction.objects.filter(tenant_id=self.tenant_id)
            .order_by("code")
            .values("id", "code", "name", "enabled", "is_temporary",
                    "reporting_manager_policy", "effective_date_rule_json",
                    "followup_policy_json", "allowed_initiators_json")
        )
        rows = []
        for a in actions:
            rows.append(
                {
                    "id": str(a["id"]),
                    "code": a["code"],
                    "name": a["name"],
                    "label": action_label(a["code"]),
                    "enabled": a["enabled"],
                    "isTemporary": a["is_temporary"],
                    "reportingManagerPolicy": a["reporting_manager_policy"],
                    "reportingManagerPolicyLabel": reporting_manager_policy_label(
                        a["reporting_manager_policy"]
                    ),
                    "effectiveDateRule": a["effective_date_rule_json"],
                    "followupPolicy": a["followup_policy_json"],
                    "allowedInitiators": a["allowed_initiators_json"] or [],
                }
            )
        return rows

    def reasons(self, action_code: str | None = None) -> list[dict]:
        qs = HrChangeReason.objects.filter(tenant_id=self.tenant_id, active=True)
        if action_code:
            qs = qs.filter(action_code=action_code)
        reasons = qs.order_by("action_code", "code").values(
            "id", "code", "name", "action_code", "requires_document",
            "requires_approval", "default_workflow_key",
            "effective_date_rule_json", "allowed_source_scope_json",
            "allowed_target_scope_json",
        )
        return [
            {
                "id": str(r["id"]),
                "code": r["code"],
                "name": r["name"],
                "actionCode": r["action_code"],
                "actionLabel": action_label(r["action_code"]),
                "requiresDocument": r["requires_document"],
                "requiresApproval": r["requires_approval"],
                "defaultWorkflowKey": r["default_workflow_key"],
                "effectiveDateRule": r["effective_date_rule_json"],
                "allowedSourceScope": r["allowed_source_scope_json"] or [],
                "allowedTargetScope": r["allowed_target_scope_json"] or [],
            }
            for r in reasons
        ]

    def field_definitions(self) -> list[dict]:
        defs = HrChangeFieldDefinition.objects.filter(tenant_id=self.tenant_id).order_by(
            "domain", "field_code"
        )
        return [
            {
                "id": str(d.id),
                "domain": d.domain,
                "fieldCode": d.field_code,
                "label": d.label,
                "legacyField": d.legacy_field,
                "authoritySource": d.authority_source,
                "editMode": d.edit_mode,
            }
            for d in defs
        ]

    def status_meta(self) -> dict:
        active = sorted(CASE_ACTIVE_STATUSES, key=str)
        terminal = sorted(CASE_TERMINAL_STATUSES, key=str)
        return {
            "activeStatuses": [
                {"code": s, "label": case_status_label(s)} for s in active
            ],
            "terminalStatuses": [
                {"code": s, "label": case_status_label(s)} for s in terminal
            ],
            "priorities": [
                {"code": c, "label": priority_label(c)} for c, _ in ChangePriority.choices
            ],
            "impactLevels": [
                {"code": c, "label": impact_level_label(c)} for c, _ in ImpactLevel.choices
            ],
            "scopes": [
                {"code": c, "label": sc} for c, sc in ChangeScopeType.choices
            ],
            "sourceAssignmentPolicies": [
                {"code": c, "label": source_assignment_policy_label(c)}
                for c, _ in SourceAssignmentPolicy.choices
            ],
            "employmentTypeChangePolicies": [
                {"code": c, "label": employment_type_change_policy_label(c)}
                for c, _ in EmploymentTypeChangePolicy.choices
            ],
        }

    def all(self) -> dict:
        return {
            "actions": self.actions(),
            "reasons": self.reasons(),
            "fieldDefinitions": self.field_definitions(),
            "statusMeta": self.status_meta(),
        }
