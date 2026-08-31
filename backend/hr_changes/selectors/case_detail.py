"""
hr_changes/selectors/case_detail.py —— 案件详情聚合（S3，只读）。

返回：摘要 / proposals / 审批快照与步骤 / 影响 / 流转时间线 / 生效快照 / 下游。
"""

from __future__ import annotations

from hr_changes.api.labels import (
    action_label,
    case_status_label,
    downstream_status_label,
    event_type_label,
    impact_level_label,
    priority_label,
)
from hr_changes.models import HrPersonnelChangeCase
from hr_changes.services.authority_receipt_service import effective_execution_chain


class CaseDetailSelector:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def get(self, case_id) -> dict | None:
        case = (
            HrPersonnelChangeCase.objects.filter(tenant_id=self.tenant_id, id=case_id)
            .select_related(
                "action_id", "reason_id", "staff_master_id", "staff_master_id__person_id",
                "source_org_id", "target_org_id", "source_position_id", "target_position_id",
            )
            .first()
        )
        if case is None:
            return None

        proposals = [
            {
                "domain": p.domain,
                "fieldCode": p.field_code,
                "oldValueRef": p.old_value_ref,
                "oldValueDisplay": p.old_value_display,
                "proposedValueRef": p.proposed_value_ref,
                "proposedValueDisplay": p.proposed_value_display,
                "effectiveAt": p.effective_at.isoformat(),
                "validationStatus": p.validation_status,
            }
            for p in case.proposals.order_by("created_at")
        ]

        approval_snapshot = None
        latest_approval = (
            case.approval_snapshots.order_by("-workflow_version").first()
        )
        if latest_approval:
            approval_snapshot = {
                "workflowVersion": latest_approval.workflow_version,
                "steps": latest_approval.steps_json,
            }

        latest_impact = case.impact_snapshots.order_by("-snapshot_version").first()
        impact = None
        if latest_impact:
            impact = {
                "snapshotVersion": latest_impact.snapshot_version,
                "blockers": [
                    {**b, "levelLabel": impact_level_label(b.get("level"))}
                    for b in latest_impact.blockers_json
                ],
                "warnings": [
                    {**w, "levelLabel": impact_level_label(w.get("level"))}
                    for w in latest_impact.warnings_json
                ],
            }

        timeline = [
            {
                "fromStatus": t.from_status,
                "fromStatusLabel": case_status_label(t.from_status),
                "toStatus": t.to_status,
                "toStatusLabel": case_status_label(t.to_status),
                "action": t.action,
                "actorId": t.actor_id,
                "actorType": t.actor_type,
                "comment": t.comment,
                "createdAt": t.created_at.isoformat(),
            }
            for t in case.transitions.order_by("created_at")
        ]

        effective_snapshot = None
        try:
            effective_snapshot = case.effective_snapshot
        except Exception:
            effective_snapshot = None
        effective = None
        if effective_snapshot:
            effective = {
                "appliedAt": effective_snapshot.applied_at.isoformat(),
                "effectiveAt": effective_snapshot.effective_at.isoformat(),
                "before": effective_snapshot.before_json,
                "after": effective_snapshot.after_json,
                "checksum": effective_snapshot.checksum,
            }

        downstream = [
            {
                "targetDomain": d.target_domain,
                "effectType": d.effect_type,
                "effectTypeLabel": event_type_label(d.effect_type),
                "status": d.status,
                "statusLabel": downstream_status_label(d.status),
                "attempts": d.attempts,
                "lastError": d.last_error,
            }
            for d in case.downstream_effects.order_by("target_domain")
        ]

        return {
            "id": str(case.id),
            "caseNo": case.case_no,
            "staffName": case.staff_master_id.person_id.legal_name,
            "staffNo": case.staff_master_id.staff_no,
            "staffId": str(case.staff_master_id_id),
            "actionCode": case.action_id.code,
            "actionLabel": action_label(case.action_id.code),
            "reasonCode": case.reason_id.code,
            "reasonName": case.reason_id.name,
            "requestedEffectiveAt": case.requested_effective_at.isoformat(),
            "approvedEffectiveAt": (
                case.approved_effective_at.isoformat() if case.approved_effective_at else None
            ),
            "status": case.status,
            "statusLabel": case_status_label(case.status),
            "priority": case.priority,
            "priorityLabel": priority_label(case.priority),
            "sourceOrg": (
                {"id": str(case.source_org_id_id), "code": case.source_org_id.stable_code}
                if case.source_org_id else None
            ),
            "targetOrg": (
                {"id": str(case.target_org_id_id), "code": case.target_org_id.stable_code}
                if case.target_org_id else None
            ),
            "sourcePosition": (
                {"id": str(case.source_position_id_id), "code": case.source_position_id.position_code}
                if case.source_position_id else None
            ),
            "targetPosition": (
                {"id": str(case.target_position_id_id), "code": case.target_position_id.position_code}
                if case.target_position_id else None
            ),
            "initiatorId": case.initiator_id,
            "ownerId": case.owner_id,
            "version": case.version,
            "proposals": proposals,
            "approvalSnapshot": approval_snapshot,
            "impact": impact,
            "timeline": timeline,
            "effectiveSnapshot": effective,
            "authorityChain": effective_execution_chain(case),
            "downstream": downstream,
        }
