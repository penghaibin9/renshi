"""
hr_contracts/services/template_governance.py

模板发布治理工作流（HR07 §28）：
DRAFT → UNDER_REVIEW → APPROVED → ACTIVE → RETIRED。
ACTIVE 后禁止直接改正文（模型 save 已拦截）；新版本 V3→V4；
历史合同绑定原 template_version（模型外键已保护）。
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from hr_contracts.api.exceptions import InvalidStateTransitionError, NotFoundError
from hr_contracts.constants import TemplateStatus
from hr_contracts.models import HrAgreementTemplate, HrAgreementTemplateVersion
from hr_contracts.services import audit_service

_VALID_TRANSITIONS = {
    TemplateStatus.DRAFT: {TemplateStatus.UNDER_REVIEW},
    TemplateStatus.UNDER_REVIEW: {TemplateStatus.APPROVED, TemplateStatus.DRAFT},
    TemplateStatus.APPROVED: {TemplateStatus.ACTIVE, TemplateStatus.DRAFT},
    TemplateStatus.ACTIVE: {TemplateStatus.RETIRED},
    TemplateStatus.RETIRED: set(),
}


class TemplateGovernanceService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.tenant_id = ctx.tenant_id

    @transaction.atomic
    def submit_for_review(self, template_id, actor=None):
        tpl = self._get_template(template_id)
        self._transition(tpl, TemplateStatus.UNDER_REVIEW, actor)
        return {"templateId": str(tpl.id), "status": tpl.status}

    @transaction.atomic
    def approve(self, template_id, actor=None):
        tpl = self._get_template(template_id)
        self._transition(tpl, TemplateStatus.APPROVED, actor)
        return {"templateId": str(tpl.id), "status": tpl.status}

    @transaction.atomic
    def publish(self, template_version_id, actor=None):
        """发布模板版本 → ACTIVE：新版本生效，旧版本 SUPERSEDED。"""
        tv = HrAgreementTemplateVersion.objects.filter(
            tenant_id=self.tenant_id, id=template_version_id
        ).first()
        if tv is None:
            raise NotFoundError("模板版本不存在")
        if tv.status != TemplateStatus.APPROVED:
            raise InvalidStateTransitionError("仅已审批版本可发布", details={"status": tv.status})

        template = tv.template_id
        # 将同模板的旧 ACTIVE 版本置为 RETIRED（不污染历史合同）
        HrAgreementTemplateVersion.objects.filter(
            tenant_id=self.tenant_id, template_id=template, status=TemplateStatus.ACTIVE
        ).update(status=TemplateStatus.RETIRED)

        tv.status = TemplateStatus.ACTIVE
        tv.approved_at = timezone.now()
        tv.save(update_fields=["status", "approved_at", "updated_at"])

        template.status = TemplateStatus.ACTIVE
        template.save(update_fields=["status", "updated_at"])

        audit_service.record(
            tenant_id=self.tenant_id, action="template.publish",
            object_type="TEMPLATE_VERSION", object_id=str(tv.id), actor_id=actor,
            after={"status": TemplateStatus.ACTIVE, "version_no": tv.version_no},
        )
        return {"templateVersionId": str(tv.id), "status": tv.status}

    @transaction.atomic
    def retire(self, template_id, actor=None):
        tpl = self._get_template(template_id)
        self._transition(tpl, TemplateStatus.RETIRED, actor)
        # 关联版本也置 RETIRED
        HrAgreementTemplateVersion.objects.filter(
            tenant_id=self.tenant_id, template_id=tpl, status=TemplateStatus.ACTIVE
        ).update(status=TemplateStatus.RETIRED)
        return {"templateId": str(tpl.id), "status": tpl.status}

    def _transition(self, tpl, new_status, actor):
        if tpl.status == new_status:
            return
        allowed = _VALID_TRANSITIONS.get(tpl.status, set())
        if new_status not in allowed:
            raise InvalidStateTransitionError(
                f"不允许从 {tpl.status} 转换到 {new_status}",
                details={"old": tpl.status, "new": new_status},
            )
        old = tpl.status
        tpl.status = new_status
        tpl.save(update_fields=["status", "updated_at"])
        audit_service.record(
            tenant_id=self.tenant_id, action=f"template.{new_status}",
            object_type="TEMPLATE", object_id=str(tpl.id), actor_id=actor,
            before={"status": old}, after={"status": new_status},
        )

    def _get_template(self, template_id) -> HrAgreementTemplate:
        tpl = HrAgreementTemplate.objects.filter(tenant_id=self.tenant_id, id=template_id).first()
        if tpl is None:
            raise NotFoundError("模板不存在")
        return tpl
