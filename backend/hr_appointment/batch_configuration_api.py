"""Canonical pre-publish configuration API for HR14 appointment batches."""

from __future__ import annotations

import uuid

from django.http import JsonResponse

from .api import HrAppointmentAccessError, _error, _payload, resolve_request_tenant
from .batch_api import _optional_datetime, _serialize
from .permissions import MANAGE_PERMISSION
from .services.batch_configuration_service import (
    AppointmentBatchConfigurationError,
    AppointmentBatchConfigurationService,
    AppointmentBatchPatch,
)


_ALLOWED_FIELDS = {
    "expectedVersion",
    "name",
    "policyVersionId",
    "businessType",
    "targetCategories",
    "targetLevels",
    "applicationFrom",
    "applicationTo",
    "publicityFrom",
    "publicityTo",
}


def _status(code: str) -> int:
    if code in {"APPOINTMENT_BATCH_NOT_FOUND", "APPOINTMENT_POLICY_NOT_FOUND"}:
        return 404
    if code in {"APPOINTMENT_BATCH_FROZEN", "APPOINTMENT_BATCH_VERSION_CONFLICT"}:
        return 409
    return 400


def update_batch(request, batch_id):
    if request.method != "PATCH":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=MANAGE_PERMISSION)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)

    unknown = set(payload) - _ALLOWED_FIELDS
    if unknown:
        return _error(
            "APPOINTMENT_BATCH_PATCH_FIELD_UNKNOWN",
            f"不支持的批次配置字段: {', '.join(sorted(unknown))}",
            status=400,
        )
    try:
        expected_version = int(payload.get("expectedVersion"))
        if expected_version < 1:
            raise ValueError
    except (TypeError, ValueError):
        return _error(
            "APPOINTMENT_BATCH_VERSION_INVALID",
            "expectedVersion 必须是正整数",
            status=400,
        )

    patch_kwargs = {}
    for api_name, service_name in (
        ("name", "name"),
        ("businessType", "business_type"),
        ("targetCategories", "target_categories"),
        ("targetLevels", "target_levels"),
    ):
        if api_name in payload:
            patch_kwargs[service_name] = payload[api_name]
    if "policyVersionId" in payload:
        try:
            patch_kwargs["policy_version_id"] = uuid.UUID(str(payload["policyVersionId"]))
        except (TypeError, ValueError, AttributeError):
            return _error(
                "APPOINTMENT_POLICY_ID_INVALID",
                "policyVersionId 必须是 UUID",
                status=400,
            )
    for api_name, service_name in (
        ("applicationFrom", "application_from"),
        ("applicationTo", "application_to"),
        ("publicityFrom", "publicity_from"),
        ("publicityTo", "publicity_to"),
    ):
        if api_name not in payload:
            continue
        try:
            patch_kwargs[service_name] = _optional_datetime(payload[api_name], field=api_name)
        except ValueError:
            return _error(
                "INVALID_DATETIME",
                f"{api_name} 必须是 ISO-8601 时间或 null",
                status=400,
            )

    try:
        batch = AppointmentBatchConfigurationService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).update_draft(
            batch_id,
            expected_version=expected_version,
            patch=AppointmentBatchPatch(**patch_kwargs),
        )
    except AppointmentBatchConfigurationError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))

    response = JsonResponse(
        {
            "data": _serialize(batch),
            "apiVersion": "1.0",
            "schemaVersion": "hr14.batch.2",
        }
    )
    response["Cache-Control"] = "no-store"
    response["ETag"] = f'"hr14-batch-v{batch.version_no}"'
    return response
