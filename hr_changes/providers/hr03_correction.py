"""HR03 formal correction provider for HR06.

HR06 owns the change/correction workflow but never writes HR03 tables.  This
provider validates the cross-module contract and invokes HR03's public
``CorrectionService`` for the actual Authority mutation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from hr_staff.services.correction_service import (
    CorrectionPolicyDenied,
    CorrectionService as HR03CorrectionService,
    CorrectionStateError,
)


HR03_CORRECTION_FIELD_ALLOWLIST = frozenset(
    {
        "person.legal_name",
        "person.preferred_name",
        "person.gender_code",
        "person.birth_date",
        "contact.mobile",
        "contact.personal_email",
        "contact.work_email",
        "contact.work_phone",
        "staff.staff_no",
        "staff.staff_category_code",
    }
)


class HR03CorrectionProviderError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class HR03CorrectionPreparation:
    items: list[dict[str, Any]]
    authority_snapshot_hash: str


@dataclass(frozen=True)
class HR03CorrectionReceipt:
    provider_case_id: str
    provider_case_no: str
    provider_case_version: int
    applied_fields: list[str]
    authority_snapshot_hash: str


class HR03CorrectionProvider:
    provider_code = "HR03_FORMAL_CORRECTION"
    provider_version = "1.0"

    _CONTACT_KIND = {
        "contact.mobile": "PERSONAL_MOBILE",
        "contact.personal_email": "PERSONAL_EMAIL",
        "contact.work_email": "WORK_EMAIL",
        "contact.work_phone": "WORK_MOBILE",
    }

    def __init__(self, tenant_id: int, actor_user_id: int | None = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    @classmethod
    def normalize_requested_values(cls, requested_values: dict) -> list[dict[str, Any]]:
        if not isinstance(requested_values, dict):
            raise HR03CorrectionProviderError(
                "CHANGE_CORRECTION_FIELDS_INVALID", "requestedValues 必须是对象"
            )

        raw_items = requested_values.get("items")
        if raw_items is None:
            fields = requested_values.get("fields")
            if fields is None and requested_values and all(
                key in HR03_CORRECTION_FIELD_ALLOWLIST for key in requested_values
            ):
                fields = requested_values
            if not isinstance(fields, dict):
                raise HR03CorrectionProviderError(
                    "CHANGE_CORRECTION_FIELDS_INVALID",
                    "requestedValues 必须包含 fields 对象或 items 数组",
                )
            raw_items = [
                {"fieldCode": field_code, "newValue": value}
                for field_code, value in fields.items()
            ]

        if not isinstance(raw_items, list) or not raw_items:
            raise HR03CorrectionProviderError(
                "CHANGE_CORRECTION_FIELDS_INVALID", "至少需要一个纠错字段"
            )

        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise HR03CorrectionProviderError(
                    "CHANGE_CORRECTION_FIELDS_INVALID", "纠错字段项必须是对象"
                )
            field_code = str(raw.get("fieldCode") or raw.get("field_code") or "").strip()
            if field_code not in HR03_CORRECTION_FIELD_ALLOWLIST:
                raise HR03CorrectionProviderError(
                    "CHANGE_CORRECTION_FIELD_DENIED", f"字段不在 HR03 纠错白名单: {field_code or '<empty>'}"
                )
            if field_code in seen:
                raise HR03CorrectionProviderError(
                    "CHANGE_CORRECTION_FIELDS_INVALID", f"纠错字段重复: {field_code}"
                )
            seen.add(field_code)
            if "newValue" not in raw and "new_value" not in raw:
                raise HR03CorrectionProviderError(
                    "CHANGE_CORRECTION_FIELDS_INVALID", f"{field_code} 缺少 newValue"
                )
            normalized.append(
                {
                    "field_code": field_code,
                    "new_value": raw.get("newValue", raw.get("new_value")),
                    "effective_date": raw.get("effectiveDate", raw.get("effective_date")),
                }
            )
        return normalized

    def prepare(
        self,
        *,
        staff,
        requested_values: dict,
        authority_version: int,
    ) -> HR03CorrectionPreparation:
        if staff.tenant_id != self.tenant_id:
            raise HR03CorrectionProviderError(
                "CROSS_TENANT_REFERENCE", "HR03 人员不属于当前学校"
            )
        if authority_version is None or int(authority_version) != staff.version:
            raise HR03CorrectionProviderError(
                "AUTHORITY_VERSION_CONFLICT", "HR03 人员版本已变化，请刷新后重试"
            )
        items = self.normalize_requested_values(requested_values)
        return HR03CorrectionPreparation(
            items=items,
            authority_snapshot_hash=self._snapshot_hash(staff, items),
        )

    def apply(self, *, correction, evidence_material_id=None) -> HR03CorrectionReceipt:
        # Read-locking an HR03 aggregate is allowed at the provider boundary;
        # every mutation below is delegated to HR03's formal service.
        from hr_staff.models import HrStaffMaster

        staff = (
            HrStaffMaster.objects.select_for_update()
            .select_related("person_id")
            .get(tenant_id=self.tenant_id, id=correction.change_case_id.staff_master_id_id)
        )
        items = self.normalize_requested_values(correction.requested_values_json)
        if int(correction.authority_version) != staff.version:
            raise HR03CorrectionProviderError(
                "AUTHORITY_VERSION_CONFLICT", "HR03 人员版本已变化，请重新发起纠错"
            )
        before_hash = self._snapshot_hash(staff, items)
        if before_hash != correction.authority_snapshot_hash:
            raise HR03CorrectionProviderError(
                "AUTHORITY_VERSION_CONFLICT", "HR03 权威事实已变化，请重新发起纠错"
            )

        hr03_items = [
            {
                "field_code": item["field_code"],
                "fact_type": item["field_code"].split(".", 1)[0],
                "new_value_masked": item["new_value"],
                "effective_date": item.get("effective_date"),
            }
            for item in items
        ]
        service = HR03CorrectionService(
            self.tenant_id, actor_user_id=self.actor_user_id
        )
        try:
            provider_case = service.create_case(
                staff_id=staff.id,
                reason=f"HR06 correction {correction.id}: {correction.reason}",
                items=hr03_items,
                evidence_material_id=evidence_material_id,
            )
            service.submit(provider_case.id)
            service.review(provider_case.id)
            service.approve(provider_case.id, approve_high_risk=True)
            provider_case.refresh_from_db()
            provider_case = service.apply(
                provider_case.id, expected_version=provider_case.version
            )
        except (CorrectionPolicyDenied, CorrectionStateError) as exc:
            raise HR03CorrectionProviderError(
                getattr(exc, "code", "HR03_CORRECTION_REJECTED"), str(exc)
            ) from exc
        except Exception as exc:
            raise HR03CorrectionProviderError(
                "HR03_CORRECTION_FAILED", str(exc)
            ) from exc

        staff.refresh_from_db()
        return HR03CorrectionReceipt(
            provider_case_id=str(provider_case.id),
            provider_case_no=provider_case.case_no,
            provider_case_version=provider_case.version,
            applied_fields=[item["field_code"] for item in items],
            authority_snapshot_hash=self._snapshot_hash(staff, items),
        )

    def _snapshot_hash(self, staff, items: list[dict[str, Any]]) -> str:
        values = {
            item["field_code"]: self._read_field(staff, item["field_code"])
            for item in items
        }
        payload = {
            "tenantId": self.tenant_id,
            "staffId": str(staff.id),
            "staffVersion": staff.version,
            "personVersion": staff.person_id.version,
            "values": values,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def _read_field(self, staff, field_code: str):
        if field_code.startswith("person."):
            return getattr(staff.person_id, field_code.split(".", 1)[1])
        if field_code.startswith("staff."):
            return getattr(staff, field_code.split(".", 1)[1])
        kind = self._CONTACT_KIND[field_code]
        contact = staff.person_id.contacts.filter(
            tenant_id=self.tenant_id, contact_kind=kind
        ).order_by("id").first()
        return contact.contact_value if contact else ""
