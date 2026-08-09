"""
hr_staff/services/outbox_service.py —— 全系统统一 outbox 发布器（§30 接线）。

所有业务 service 事实变化后调用本模块的 emit_xxx，不再散写 HrOutboxEvent.objects.create。
"""

from __future__ import annotations

import uuid
from typing import Optional

from hr_staff.models import HrOutboxEvent


def _emit(tenant_id: int, event_type: str, payload: dict, correlation_id: str = ""):
    return HrOutboxEvent.objects.create(
        tenant_id=tenant_id,
        event_type=event_type,
        payload_json=payload,
        correlation_id=correlation_id or uuid.uuid4().hex[:12],
    )


def staff_master_created(tenant_id: int, staff_id, staff_no: str, source: str = ""):
    _emit(tenant_id, "StaffCreated", {"staffId": str(staff_id), "staffNo": staff_no, "source": source})


def staff_activated(tenant_id: int, staff_id, effective_from):
    _emit(tenant_id, "StaffActivated", {"staffId": str(staff_id), "effectiveDate": str(effective_from)})


def staff_status_changed(tenant_id: int, staff_id, old_status: str, new_status: str):
    _emit(tenant_id, "StaffStatusChanged", {"staffId": str(staff_id), "oldStatus": old_status, "newStatus": new_status})


def relationship_started(tenant_id: int, staff_id, relationship_id, relationship_type: str, effective_from):
    _emit(tenant_id, "EmploymentRelationshipStarted", {
        "staffId": str(staff_id), "relationshipId": str(relationship_id),
        "relationshipType": relationship_type, "effectiveDate": str(effective_from),
    })


def relationship_ended(tenant_id: int, staff_id, relationship_id, effective_to, reason_code: str = ""):
    _emit(tenant_id, "EmploymentRelationshipEnded", {
        "staffId": str(staff_id), "relationshipId": str(relationship_id),
        "effectiveDate": str(effective_to), "reasonCode": reason_code,
    })


def primary_assignment_changed(tenant_id: int, staff_id, assignment_id, effective_from):
    _emit(tenant_id, "PrimaryAssignmentChanged", {
        "staffId": str(staff_id), "assignmentId": str(assignment_id), "effectiveDate": str(effective_from),
    })


def concurrent_assignment_changed(tenant_id: int, staff_id, assignment_id, effective_from):
    _emit(tenant_id, "ConcurrentAssignmentChanged", {
        "staffId": str(staff_id), "assignmentId": str(assignment_id), "effectiveDate": str(effective_from),
    })


def staff_basic_info_corrected(tenant_id: int, staff_id, correction_case_id, fields: list):
    _emit(tenant_id, "StaffBasicInfoCorrected", {
        "staffId": str(staff_id), "correctionCaseId": str(correction_case_id), "changedFields": fields,
    })


def staff_credential_changed(tenant_id: int, staff_id, credential_id, credential_name: str = ""):
    _emit(tenant_id, "StaffCredentialChanged", {
        "staffId": str(staff_id), "credentialId": str(credential_id), "credentialName": credential_name,
    })


def staff_material_verified(tenant_id: int, staff_id, material_id):
    _emit(tenant_id, "StaffMaterialVerified", {
        "staffId": str(staff_id), "materialId": str(material_id),
    })


def staff_authority_mode_changed(tenant_id: int, mode: str, reason: str = ""):
    _emit(tenant_id, "StaffAuthorityModeChanged", {"mode": mode, "reason": reason})
