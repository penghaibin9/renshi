"""
hr_changes/selectors/bootstrap_data.py —— HR06 bootstrap 数据（S1）。

提供：动作/原因/受管字段/状态元数据；全部按 tenant 隔离 + 中文 label 成对。
"""

from __future__ import annotations

from hr_changes.api.labels import (
    action_label,
    case_status_label,
    employment_type_change_policy_label,
    employment_type_label,
    impact_level_label,
    priority_label,
    relationship_type_label,
    reporting_manager_policy_label,
    source_assignment_policy_label,
    staff_category_label,
)
from hr_changes.constants import (
    CASE_ACTIVE_STATUSES,
    CASE_TERMINAL_STATUSES,
    ChangePriority,
    ChangeScopeType,
    EmploymentTypeChangePolicy,
    ImpactLevel,
    SourceAssignmentPolicy,
)
from hr_changes.models import HrChangeAction, HrChangeFieldDefinition, HrChangeReason
from hr_staff.constants import EmploymentType, RelationshipType, StaffCategoryCode


class BootstrapDataSelector:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def actions(self) -> list[dict]:
        actions = (
            HrChangeAction.objects.filter(tenant_id=self.tenant_id)
            .order_by("code")
            .values(
                "id",
                "code",
                "name",
                "enabled",
                "is_temporary",
                "reporting_manager_policy",
                "effective_date_rule_json",
                "followup_policy_json",
                "allowed_initiators_json",
            )
        )
        rows = []
        for action in actions:
            rows.append(
                {
                    "id": str(action["id"]),
                    "code": action["code"],
                    "name": action["name"],
                    "label": action_label(action["code"]),
                    "enabled": action["enabled"],
                    "isTemporary": action["is_temporary"],
                    "reportingManagerPolicy": action["reporting_manager_policy"],
                    "reportingManagerPolicyLabel": reporting_manager_policy_label(
                        action["reporting_manager_policy"]
                    ),
                    "effectiveDateRule": action["effective_date_rule_json"],
                    "followupPolicy": action["followup_policy_json"],
                    "allowedInitiators": action["allowed_initiators_json"] or [],
                }
            )
        return rows

    def reasons(self, action_code: str | None = None) -> list[dict]:
        qs = HrChangeReason.objects.filter(tenant_id=self.tenant_id, active=True)
        if action_code:
            qs = qs.filter(action_code=action_code)
        reasons = qs.order_by("action_code", "code").values(
            "id",
            "code",
            "name",
            "action_code",
            "requires_document",
            "requires_approval",
            "default_workflow_key",
            "effective_date_rule_json",
            "allowed_source_scope_json",
            "allowed_target_scope_json",
        )
        return [
            {
                "id": str(reason["id"]),
                "code": reason["code"],
                "name": reason["name"],
                "actionCode": reason["action_code"],
                "actionLabel": action_label(reason["action_code"]),
                "requiresDocument": reason["requires_document"],
                "requiresApproval": reason["requires_approval"],
                "defaultWorkflowKey": reason["default_workflow_key"],
                "effectiveDateRule": reason["effective_date_rule_json"],
                "allowedSourceScope": reason["allowed_source_scope_json"] or [],
                "allowedTargetScope": reason["allowed_target_scope_json"] or [],
            }
            for reason in reasons
        ]

    def field_definitions(self) -> list[dict]:
        definitions = HrChangeFieldDefinition.objects.filter(
            tenant_id=self.tenant_id
        ).order_by("domain", "field_code")
        return [
            {
                "id": str(definition.id),
                "domain": definition.domain,
                "fieldCode": definition.field_code,
                "label": definition.label,
                "legacyField": definition.legacy_field,
                "authoritySource": definition.authority_source,
                "editMode": definition.edit_mode,
            }
            for definition in definitions
        ]

    def identity_options(self) -> dict:
        """只暴露 HR03 受控枚举；浏览器不自行维护机器值。"""
        from hr_structure.models import HrOrganizationVersion

        location_codes = list(
            HrOrganizationVersion.objects.filter(
                tenant_id=self.tenant_id,
                status="EFFECTIVE",
            )
            .exclude(location_code="")
            .order_by("location_code")
            .values_list("location_code", flat=True)
            .distinct()[:300]
        )
        return {
            "staffCategories": [
                {"code": code, "label": staff_category_label(code)}
                for code, _ in StaffCategoryCode.choices
            ],
            "relationshipTypes": [
                {"code": code, "label": relationship_type_label(code)}
                for code, _ in RelationshipType.choices
            ],
            "employmentTypes": [
                {"code": code, "label": employment_type_label(code)}
                for code, _ in EmploymentType.choices
            ],
            "workLocations": [
                {"code": code, "label": code} for code in location_codes
            ],
        }

    def status_meta(self) -> dict:
        active = sorted(CASE_ACTIVE_STATUSES, key=str)
        terminal = sorted(CASE_TERMINAL_STATUSES, key=str)
        return {
            "activeStatuses": [
                {"code": status, "label": case_status_label(status)} for status in active
            ],
            "terminalStatuses": [
                {"code": status, "label": case_status_label(status)}
                for status in terminal
            ],
            "priorities": [
                {"code": code, "label": priority_label(code)}
                for code, _ in ChangePriority.choices
            ],
            "impactLevels": [
                {"code": code, "label": impact_level_label(code)}
                for code, _ in ImpactLevel.choices
            ],
            "scopes": [
                {"code": code, "label": label}
                for code, label in ChangeScopeType.choices
            ],
            "sourceAssignmentPolicies": [
                {"code": code, "label": source_assignment_policy_label(code)}
                for code, _ in SourceAssignmentPolicy.choices
            ],
            "employmentTypeChangePolicies": [
                {"code": code, "label": employment_type_change_policy_label(code)}
                for code, _ in EmploymentTypeChangePolicy.choices
            ],
        }

    def all(self) -> dict:
        return {
            "actions": self.actions(),
            "reasons": self.reasons(),
            "fieldDefinitions": self.field_definitions(),
            "identityOptions": self.identity_options(),
            "statusMeta": self.status_meta(),
        }
