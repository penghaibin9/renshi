"""
hr_staff/services/event_service.py —— 业务域事件接收 + outbox 发布（S10）。

硬合同：
- 生效事实接收：HR05_ONBOARDING/HR06_TRANSFER/HR06_POSITION_CHANGE/HR07_CONTRACT/
  HR13_TITLE_APPOINTMENT/HR14_APPOINTMENT/HR16_EXIT/HR16_REHIRE；
- 幂等：idempotency_key = f"{source_business_type}:{source_business_id}" 唯一，重复消费不重复写；
- HR16 离职/退休：关关系+关任职段+状态段，历史保留，不 DELETE；
- HR13/HR14 结果以 projection/fact reference 接收，不反向改评审过程记录；
- 事件写与 authority 写同事务（outbox 模式）。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import IntegrityError, transaction

from hr_staff.constants import AssignmentType, SourceBusinessType, StaffStatus
from hr_staff.models import HrBusinessEventInbox, HrOutboxEvent
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.services.staff_master_service import StaffMasterService

from hr_staff.services.person_identity_service import PersonIdentityService


class EventConsumptionError(Exception):
    code = "EVENT_CONSUMPTION_FAILED"


# 99 总册 GlobalEventRegistry（PATCH-05）：canonical 事件名 → 本地 handler 名。
# HR05/HR06/HR13/HR14/HR16 生产方按 canonical 名发布；旧风格名（HR05_ONBOARDING 等）保留兼容。
CANONICAL_EVENT_HANDLERS = {
    "StaffActivated": "_on_hr05_onboarding",
    "PersonnelChangeEffective": "_on_hr06_transfer",
    "ContractEffective": "_on_hr07_contract",
    "ContractTerminated": "_on_hr07_contract",
    "ProfessionalTitleResultEffective": "_on_hr13_title_appointment",
    "ProfessionalTitleResultRevised": "_on_hr13_title_appointment",
    "ProfessionalTitleResultRevoked": "_on_hr13_title_appointment",
    "PositionAppointmentEffective": "_on_hr14_appointment",
    "ExitEffective": "_on_hr16_exit",
    "RetirementEffective": "_on_hr16_exit",
}


class BusinessEventService:
    """HR 业务域 → HR03 生效事实消费者。"""

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    # ------------------------------------------------------------------
    # 接收（幂等）
    # ------------------------------------------------------------------
    @transaction.atomic
    def receive(self, *, event_type: str, payload: dict) -> HrBusinessEventInbox:
        """接收事件；重复 idempotency_key → 返回既有事件（不重复处理）。"""
        payload = self._jsonable(payload)
        source_business_type = payload.get("source_business_type", event_type)
        source_business_id = payload.get("source_business_id", "")
        idempotency_key = f"{source_business_type}:{source_business_id}"
        existing = HrBusinessEventInbox.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing
        try:
            return HrBusinessEventInbox.objects.create(
                tenant_id=self.tenant_id,
                event_type=event_type,
                source_business_type=source_business_type,
                source_business_id=source_business_id,
                payload_json=payload,
                idempotency_key=idempotency_key,
            )
        except IntegrityError:
            return HrBusinessEventInbox.objects.get(idempotency_key=idempotency_key)

    @staticmethod
    def _jsonable(obj):
        """深度 JSON 序列化：UUID→str，date→ISO，其余原样。"""
        import datetime
        import uuid as _uuid

        if isinstance(obj, _uuid.UUID):
            return str(obj)
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: BusinessEventService._jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [BusinessEventService._jsonable(v) for v in obj]
        return obj

    # ------------------------------------------------------------------
    # 消费（按事件类型分发）
    # ------------------------------------------------------------------
    def consume(self, inbox_id) -> HrBusinessEventInbox:
        # 状态标记与失败落库独立于应用事务（P2-2：失败可追踪，不被回滚吞掉）
        with transaction.atomic():
            inbox = (
                HrBusinessEventInbox.objects.select_for_update()
                .filter(tenant_id=self.tenant_id, id=inbox_id)
                .first()
            )
            if inbox is None:
                raise EventConsumptionError("INBOX_NOT_FOUND")
            if inbox.status == "CONSUMED":
                return inbox
            inbox.status = "PROCESSING"
            inbox.attempts += 1
            inbox.save(update_fields=["status", "attempts"])
        try:
            with transaction.atomic():
                handler_name = CANONICAL_EVENT_HANDLERS.get(
                    inbox.event_type, f"_on_{inbox.event_type.lower()}"
                )
                handler = getattr(self, handler_name, None)
                if handler is None:
                    raise EventConsumptionError(f"UNSUPPORTED_EVENT: {inbox.event_type}")
                handler(inbox.payload_json)
                inbox.status = "CONSUMED"
                from django.utils import timezone

                inbox.consumed_at = timezone.now()
                inbox.last_error = ""
                inbox.save(update_fields=["status", "consumed_at", "last_error"])
        except Exception as exc:
            # 独立落库，不被应用事务回滚
            HrBusinessEventInbox.objects.filter(pk=inbox.pk).update(
                status="FAILED",
                last_error=f"{exc.__class__.__name__}: {exc}",
            )
            raise EventConsumptionError(f"{exc}")
        return inbox

    # ------------------------------------------------------------------
    # 事件处理器
    # ------------------------------------------------------------------
    def _resolve_staff(self, staff_id):
        """payload 中的 staff_id（str/UUID）→ HrStaffMaster 实例。"""
        from hr_staff.models import HrStaffMaster

        if isinstance(staff_id, HrStaffMaster):
            return staff_id
        return HrStaffMaster.objects.filter(tenant_id=self.tenant_id, id=staff_id).first()

    def _resolve_org(self, organization_id):
        """P1-a：payload 中的 organization_id（int PK/str）→ HrOrganization 实例（tenant 校验）。"""
        if not organization_id:
            return None
        from hr_structure.models import HrOrganization

        if isinstance(organization_id, HrOrganization):
            return organization_id if organization_id.tenant_id == self.tenant_id else None
        return HrOrganization.objects.filter(tenant_id=self.tenant_id, id=organization_id).first()

    def _on_hr05_onboarding(self, payload):
        """HR05 正式入职：Person(已建) + Staff + Relationship + PRIMARY Assignment。"""
        staff = self._resolve_staff(payload.get("staff_id"))
        if staff is None:
            raise EventConsumptionError("STAFF_NOT_FOUND")
        relationship_type = payload.get("relationship_type", "REGULAR_EMPLOYMENT")
        effective_from = date.fromisoformat(payload["effective_from"])
        emp = EmploymentService(self.tenant_id, self.actor_user_id).start_relationship(
            staff_id=staff,
            relationship_type=relationship_type,
            employment_type=payload.get("employment_type", ""),
            effective_from=effective_from,
            source_business_type="HR05_ONBOARDING",
            source_business_id=payload.get("source_business_id", ""),
        )
        AssignmentService(self.tenant_id, audit_actor_user_id=self.actor_user_id).create_assignment(
            employment_relationship_id=emp,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=effective_from,
            organization_id=self._resolve_org(payload.get("organization_id")),
            legacy_department_id=payload.get("legacy_department_id"),
            source_business_type="HR05_ONBOARDING",
            source_business_id=payload.get("source_business_id", ""),
        )

    def _on_hr06_transfer(self, payload):
        """HR06 调动：switch_primary 原子切换。"""
        rel_id = payload.get("employment_relationship_id")
        effective_from = date.fromisoformat(payload["effective_from"])
        AssignmentService(self.tenant_id, audit_actor_user_id=self.actor_user_id).switch_primary(
            employment_relationship_id=rel_id,
            effective_from=effective_from,
            organization_id=self._resolve_org(payload.get("organization_id")),
            legacy_department_id=payload.get("legacy_department_id"),
            source_business_type="HR06_TRANSFER",
            source_business_id=payload.get("source_business_id", ""),
        )

    def _on_hr06_position_change(self, payload):
        self._on_hr06_transfer(payload)

    def _on_hr07_contract(self, payload):
        """HR07 合同生效：更新关系有效事实（不复制合同正文）。"""
        rel_id = payload.get("employment_relationship_id")
        # [总控占位] 合同到期日投影到关系段；正文归 HR07，HR03 只收生效事实
        if payload.get("contract_end_date"):
            from hr_staff.models import HrEmploymentRelationship

            rel = HrEmploymentRelationship.objects.filter(
                tenant_id=self.tenant_id, id=rel_id
            ).first()
            if rel:
                rel.reason_code = payload.get("reason_code", rel.reason_code)
                rel.save(update_fields=["reason_code"])

    def _on_hr13_title_appointment(self, payload):
        """HR13 职称评审生效：写入资格事实投影（不复制评审过程）。"""
        staff = self._resolve_staff(payload.get("staff_id"))
        if staff is None:
            raise EventConsumptionError("STAFF_NOT_FOUND")
        from hr_staff.services.background_service import BackgroundService

        BackgroundService(self.tenant_id, self.actor_user_id, has_manage_perm=True).add_credential(
            staff_id=staff,
            credential_type="PROFESSIONAL_CERTIFICATE",
            credential_name=payload.get("title_name", "专业技术职务"),
            level=payload.get("title_level", ""),
            issuing_authority=payload.get("issuing_authority", ""),
            issue_date=date.fromisoformat(payload["effective_date"]) if payload.get("effective_date") else None,
            source_domain="HR13",
        )

    def _on_hr14_appointment(self, payload):
        """HR14 岗位聘任生效：接收新的岗位任职事实。"""
        self._on_hr06_transfer(payload)

    def _on_hr16_exit(self, payload):
        """HR16 离职/退休：关关系+关任职段+状态段；历史保留，不 DELETE。"""
        rel_id = payload.get("employment_relationship_id")
        effective_to = date.fromisoformat(payload["effective_to"])
        reason_code = payload.get("reason_code", "EXIT")
        EmploymentService(self.tenant_id, self.actor_user_id).end_relationship(
            relationship_id=rel_id,
            effective_to=effective_to,
            reason_code=reason_code,
            source_business_type="HR16_EXIT",
            source_business_id=payload.get("source_business_id", ""),
        )
        staff = self._resolve_staff(payload.get("staff_id"))
        if staff and reason_code.upper().startswith("RETIRE"):
            from hr_staff.models import HrStatusHistory

            HrStatusHistory.objects.create(
                tenant_id=self.tenant_id,
                staff_id=staff,
                status_code=StaffStatus.RETIRED,
                effective_from=effective_to,
                reason_code=reason_code,
            )

    def _on_hr16_rehire(self, payload):
        """HR16 返聘：同 Person 新关系（不重复 Person）。"""
        self._on_hr05_onboarding(payload)

    # ------------------------------------------------------------------
    # Outbox（向外发布）
    # ------------------------------------------------------------------
    def emit(self, *, event_type: str, payload: dict, correlation_id: str = "") -> HrOutboxEvent:
        from hr_staff.services.outbox_service import _emit

        return _emit(
            self.tenant_id,
            event_type,
            payload,
            correlation_id,
        )
