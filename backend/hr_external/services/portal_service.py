"""
hr_external/services/portal_service.py —— 外聘本人门户（B6，总册 §90/§55）。

- 本人门户只允许本人数据（§90）：profile 必要部分/engagement/task/协议可见版本/workload；
  不允许其他外聘教师/正式员工信息/HR reviewer notes/敏感合规内部结论。
- token：SHA-256 存储，明文只签发一次（对齐 HR05 token_service 模式）；公开入口凭 token 解析学校（00 §134）。
- 本人可提交任务证据/更新本人意愿，但不得改正式结论（只走 service 状态机）。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from hr_external.constants import ExternalEngagementStatus
from hr_external.models import (
    HrExternalEngagement,
    HrExternalPortalToken,
    HrExternalServiceTask,
    HrExternalTeacherProfile,
    HrExternalWorkloadRecord,
)

PORTAL_TOKEN_TTL_HOURS = 24


class PortalTokenInvalid(Exception):
    code = "PORTAL_TOKEN_INVALID"


class PortalDataDenied(Exception):
    code = "EXTERNAL_SCOPE_DENIED"


class PortalService:
    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def issue_token(
        self,
        *,
        tenant_id: int,
        external_profile_id,
        issued_by: Optional[int] = None,
    ) -> tuple[str, HrExternalPortalToken]:
        """签发 portal token：返回明文一次（调用方负责交付本人），库中只存 hash。"""
        profile = HrExternalTeacherProfile.objects.filter(
            tenant_id=tenant_id, id=external_profile_id
        ).first()
        if profile is None:
            raise PortalDataDenied("external profile not found inside tenant")
        raw = secrets.token_urlsafe(32)
        token = HrExternalPortalToken.objects.create(
            tenant_id=tenant_id,
            external_profile_id=profile,
            token_hash=self._hash(raw),
            expires_at=timezone.now() + timedelta(hours=PORTAL_TOKEN_TTL_HOURS),
            issued_by=issued_by,
        )
        return raw, token

    def resolve_token(self, *, raw: str) -> HrExternalTeacherProfile:
        """凭 token 解析本人 profile（公开入口，token 内含 tenant 归属）。"""
        token = HrExternalPortalToken.objects.select_related("external_profile_id").filter(
            token_hash=self._hash(raw), status="ACTIVE"
        ).first()
        if token is None:
            raise PortalTokenInvalid("token invalid or not active")
        if token.expires_at < timezone.now():
            token.status = "EXPIRED"
            token.save(update_fields=["status"])
            raise PortalTokenInvalid("token expired")
        return token.external_profile_id

    def me(self, *, profile: HrExternalTeacherProfile) -> dict:
        """本人视图（§90）：只暴露本人数据，不含敏感合规内部结论。"""
        tenant_id = profile.tenant_id
        engagements = HrExternalEngagement.objects.filter(
            tenant_id=tenant_id, external_profile_id=profile
        ).order_by("-start_at")
        active_eng_ids = [str(e.id) for e in engagements if e.status == ExternalEngagementStatus.ACTIVE]
        tasks = HrExternalServiceTask.objects.filter(
            tenant_id=tenant_id, engagement_id__external_profile_id=profile
        ).order_by("-updated_at")[:100]
        workload = HrExternalWorkloadRecord.objects.filter(
            tenant_id=tenant_id, engagement_id__external_profile_id=profile
        ).order_by("-service_date")[:100]

        return {
            "profile": {
                "externalTeacherNo": profile.external_teacher_no,
                "legalName": profile.person_id.legal_name,
                "category": profile.primary_category.name if profile.primary_category else "",
            },
            "engagements": [
                {
                    "id": str(e.id),
                    "engagementNo": e.engagement_no,
                    "status": e.status,
                    "startAt": e.start_at.isoformat(),
                    "endAt": e.end_at.isoformat() if e.end_at else None,
                    "agreementStatus": e.agreement_status,
                }
                for e in engagements
            ],
            "activeEngagementIds": active_eng_ids,
            "tasks": [
                {
                    "id": str(t.id),
                    "taskType": t.task_type,
                    "title": t.title,
                    "status": t.status,
                    "acceptance": t.acceptance,
                    "plannedStart": t.planned_start.isoformat(),
                    "plannedEnd": t.planned_end.isoformat() if t.planned_end else None,
                    "sourceDomain": t.source_domain,
                }
                for t in tasks
            ],
            "workload": [
                {
                    "id": str(w.id),
                    "quantity": float(w.quantity),
                    "unit": w.unit,
                    "serviceDate": w.service_date.isoformat(),
                    "verificationStatus": w.verification_status,
                    "settlementStatus": w.settlement_status,
                }
                for w in workload
            ],
        }
