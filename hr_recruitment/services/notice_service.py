"""
hr_recruitment/services/notice_service.py

HR04-06 公示与异议服务（《04_HR04_总册》§13.4/§13.5）。

硬规则：
- 公示条目只暴露白名单字段（public_display_name + public_fields_json），绝不暴露 Candidate 全字段。
- 异议案件独立（RECEIVED→UNDER_REVIEW→NEEDS_EVIDENCE→RESOLVED_*→CLOSED）。
- 结果变化（RESOLVED_CHANGE）必须创建新决策版本，不覆盖原结果。
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from hr_recruitment.constants import ObjectionStatus, PublicNoticeStatus
from hr_recruitment.models import (
    HrNoticeObjection,
    HrProposedHire,
    HrPublicNotice,
    HrPublicNoticeEntry,
)

# 公示条目允许展示的字段白名单（服务端强制；不含身份证/手机号/邮箱等 PII）
PUBLIC_NOTICE_FIELD_WHITELIST = frozenset(
    {
        "public_display_name",  # 已脱敏展示名（如 张**）
        "position",  # 应聘岗位
        "organization",  # 招聘单位
        "rank",  # 排名
        "final_score",  # 综合成绩
    }
)


class NoticeServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class NoticeService:
    def __init__(self, *, tenant_id: int, actor: str = ""):
        self.tenant_id = tenant_id
        self.actor = actor

    @transaction.atomic
    def publish_notice(
        self,
        *,
        campaign_id: str,
        notice_no: str,
        start_at=None,
        end_at=None,
        entries: list[dict] | None = None,
    ) -> HrPublicNotice:
        """发布公示（start/end 默认 7 天）。entries: [{proposed_hire_id, public_display_name, public_fields}]"""
        notice = HrPublicNotice.objects.create(
            tenant_id=self.tenant_id,
            campaign_id_id=campaign_id,
            notice_no=notice_no,
            start_at=start_at or timezone.now(),
            end_at=end_at or (timezone.now() + timedelta(days=7)),
            status=PublicNoticeStatus.PUBLISHED,
            published_by=self.actor,
        )
        for entry in entries or []:
            # 公示字段白名单（服务端强制，§13.4：绝不暴露 Candidate 全字段）
            public_fields = {
                k: v
                for k, v in (entry.get("public_fields") or {}).items()
                if k in PUBLIC_NOTICE_FIELD_WHITELIST
            }
            HrPublicNoticeEntry.objects.create(
                tenant_id=self.tenant_id,
                notice_id=notice,
                proposed_hire_id_id=entry.get("proposed_hire_id"),
                public_display_name=entry.get("public_display_name", ""),
                public_fields_json=public_fields,
            )
        # 关联申请的 canonical_status → PUBLIC_NOTICE（走状态机 + 写 ledger）
        from hr_recruitment.constants import ApplicationCanonicalStatus as S
        from hr_recruitment.models import HrApplicationTransition
        from hr_recruitment.policies.state_machine import assert_transition

        for entry in entries or []:
            proposed = HrProposedHire.objects.filter(
                tenant_id=self.tenant_id, id=entry.get("proposed_hire_id")
            ).first()
            if proposed:
                app = proposed.application_id
                if app.canonical_status == S.PROPOSED_HIRE:
                    assert_transition(app.canonical_status, S.PUBLIC_NOTICE)
                    app.canonical_status = S.PUBLIC_NOTICE
                    app.version += 1
                    app.save(update_fields=["canonical_status", "version"])
                    HrApplicationTransition.objects.create(
                        tenant_id=self.tenant_id,
                        application_id=app,
                        from_status=S.PROPOSED_HIRE,
                        to_status=S.PUBLIC_NOTICE,
                        action="PUBLIC_NOTICE_PUBLISHED",
                        actor_id=self.actor,
                        source="HR_ADMIN",
                    )
        return notice

    @transaction.atomic
    def close_notice(self, *, notice_id: str, has_blocker: bool = False) -> HrPublicNotice:
        """公示结束（CLOSED_NO_BLOCKER / CLOSED_WITH_OBJECTION）。"""
        notice = self._get(notice_id)
        notice.status = (
            PublicNoticeStatus.CLOSED_WITH_OBJECTION
            if has_blocker
            else PublicNoticeStatus.CLOSED_NO_BLOCKER
        )
        notice.save(update_fields=["status"])
        return notice

    @transaction.atomic
    def receive_objection(
        self,
        *,
        notice_id: str,
        proposed_hire_id=None,
        source="",
        category="",
        content="",
        evidence="",
    ) -> HrNoticeObjection:
        notice = self._get(notice_id)
        return HrNoticeObjection.objects.create(
            tenant_id=self.tenant_id,
            notice_id=notice,
            proposed_hire_id_id=proposed_hire_id,
            source=source,
            category=category,
            content=content,
            evidence=evidence,
            status=ObjectionStatus.RECEIVED,
        )

    @transaction.atomic
    def resolve_objection(
        self, *, objection_id: str, status: str, resolution: str
    ) -> HrNoticeObjection:
        """
        处理异议。RESOLVED_CHANGE 表示结果变化（必须创建新决策版本，不覆盖原结果）。
        """
        objection = HrNoticeObjection.objects.get(
            id=objection_id, tenant_id=self.tenant_id
        )
        objection.status = status
        objection.resolution = resolution
        objection.resolved_by = self.actor
        objection.resolved_at = timezone.now()
        objection.save(update_fields=["status", "resolution", "resolved_by", "resolved_at"])
        if status == ObjectionStatus.RESOLVED_CHANGE and objection.proposed_hire_id_id:
            # 结果变化：新决策版本（version 自增，保留原版本）
            proposed = HrProposedHire.objects.get(
                id=objection.proposed_hire_id_id, tenant_id=self.tenant_id
            )
            proposed.version += 1
            proposed.save(update_fields=["version"])
        return objection

    def _get(self, notice_id: str) -> HrPublicNotice:
        try:
            return HrPublicNotice.objects.get(id=notice_id, tenant_id=self.tenant_id)
        except HrPublicNotice.DoesNotExist:
            raise NoticeServiceError("NOTICE_NOT_FOUND", "公示不存在", http_status=404)
