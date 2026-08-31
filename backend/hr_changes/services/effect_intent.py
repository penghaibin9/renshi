"""Canonical hash of the approved HR06 intent and approval chain."""

import hashlib
import json


def effect_intent_payload(case, approval) -> dict:
    proposals = [
        {
            "id": str(item.id),
            "domain": item.domain,
            "fieldCode": item.field_code,
            "oldValueRef": item.old_value_ref,
            "proposedValueRef": item.proposed_value_ref,
            "effectiveAt": item.effective_at.isoformat(),
            "sourceFactId": item.source_fact_id,
            "metadata": item.metadata_json or {},
        }
        for item in case.proposals.order_by("domain", "field_code", "id")
    ]
    return {
        "tenantId": int(case.tenant_id),
        "caseId": str(case.id),
        "staffId": str(case.staff_master_id_id),
        "employmentRelationshipId": (
            str(case.employment_relationship_id_id)
            if case.employment_relationship_id_id
            else None
        ),
        "sourceAssignmentId": (
            str(case.source_assignment_id_id) if case.source_assignment_id_id else None
        ),
        "actionId": str(case.action_id_id),
        "actionCode": case.action_id.code,
        "reasonId": str(case.reason_id_id),
        "requestedEffectiveAt": case.requested_effective_at.isoformat(),
        "approvedEffectiveAt": (
            case.approved_effective_at.isoformat()
            if case.approved_effective_at
            else case.requested_effective_at.isoformat()
        ),
        "sourceOrgId": str(case.source_org_id_id) if case.source_org_id_id else None,
        "targetOrgId": str(case.target_org_id_id) if case.target_org_id_id else None,
        "sourcePositionId": (
            str(case.source_position_id_id) if case.source_position_id_id else None
        ),
        "targetPositionId": (
            str(case.target_position_id_id) if case.target_position_id_id else None
        ),
        "approvalSnapshotId": str(approval.id),
        "workflowVersion": approval.workflow_version,
        "approvalSteps": approval.steps_json or [],
        "proposals": proposals,
    }


def effect_intent_hash(case, approval) -> str:
    encoded = json.dumps(
        effect_intent_payload(case, approval),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
