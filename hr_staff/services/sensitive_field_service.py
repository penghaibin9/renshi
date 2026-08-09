"""
hr_staff/services/sensitive_field_service.py —— 高敏字段 reveal（总册 §29，补接线）。

硬合同：
- 高敏字段不随 profile bootstrap 下发；查看走 POST reveal endpoint；
- 必须 purpose + 独立权限（hr.staff.reveal_high_sensitive / hr.staff.view_sensitive）+ 审计（HrSensitiveAccessLog）；
- 前端 60 秒后自动重新遮罩；页面失焦可立即遮罩；禁止写入 localStorage/sessionStorage；
- 搜索：普通 keyword 不支持身份证明文模糊搜索；身份证查人走专门 exact endpoint（见 staff_api）。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.utils import timezone

from hr_staff.constants import SensitivityLevel
from hr_staff.models import HrSensitiveAccessLog
from hr_staff.services.audit_service import write_audit_event
from hr_staff.services.common import resolve_staff
from hr_staff.services.crypto import decrypt_document_number


class SensitiveFieldDenied(Exception):
    code = "SENSITIVE_FIELD_DENIED"


class SensitiveFieldNotFound(Exception):
    code = "SENSITIVE_FIELD_NOT_FOUND"


class SensitiveFieldService:
    """高敏字段查看服务（带审计与时效遮罩）。"""

    DEFAULT_EXPIRES_SECONDS = 60

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None, context=None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id
        self.context = context  # HrStaffRequestContext（可选；提供则做 data scope 校验）

    def reveal(
        self,
        *,
        staff_id,
        field_code: str,
        purpose: str,
        has_permission: bool,
    ) -> dict:
        """查看一个高敏字段明文。返回 value + expiresAt（前端 60s 遮罩）。"""
        if not has_permission:
            raise SensitiveFieldDenied("无权限查看该敏感字段")
        if not purpose.strip():
            raise SensitiveFieldDenied("必须填写查看用途（purpose）")

        staff = resolve_staff(self.tenant_id, staff_id)  # P1-6 跨租户
        if self.context is not None:
            from hr_staff.policies.scope_policy import ScopeEnforcer

            ScopeEnforcer(self.context).assert_accessible(staff)  # P1-5

        value = self._resolve_value(staff, field_code)
        if value is None:
            raise SensitiveFieldNotFound(f"字段 {field_code} 无数据或不可查看")

        expires_at = timezone.now() + timedelta(seconds=self.DEFAULT_EXPIRES_SECONDS)
        HrSensitiveAccessLog.objects.create(
            tenant_id=self.tenant_id,
            staff_id=staff.id,
            field_code=field_code,
            actor_user_id=self.actor_user_id,
            purpose=purpose,
            action="REVEAL",
            expires_at=expires_at,
        )
        write_audit_event(
            tenant_id=self.tenant_id,
            action="SensitiveFieldRevealed",
            actor_user_id=self.actor_user_id,
            staff_id=staff.id,
            reason=f"{field_code} reveal, purpose={purpose[:200]}",
        )
        return {
            "value": value,
            "expiresAt": expires_at.isoformat(),
            "maskAfterSeconds": self.DEFAULT_EXPIRES_SECONDS,
        }

    def _resolve_value(self, staff, field_code: str) -> Optional[str]:
        """解析明文（V1 支持 identity.document_number；其余字段默认不可 reveal）。"""
        from hr_staff.models import HrPersonIdentityDocument

        if field_code == "identity.document_number":
            doc = (
                HrPersonIdentityDocument.objects.filter(
                    tenant_id=self.tenant_id,
                    person_id=staff.person_id,
                    document_number_ciphertext__isnull=False,
                )
                .exclude(document_number_ciphertext="")
                .first()
            )
            if doc is None:
                return None
            return decrypt_document_number(doc.document_number_ciphertext)

        if field_code in ("person.birth_date", "contact.personal_mobile", "contact.personal_email"):
            # 这些字段在 bootstrap 已按掩码展示；如需明文 reveal，按 SENSITIVE/RESTRICTED 权限扩展
            return None

        return None
