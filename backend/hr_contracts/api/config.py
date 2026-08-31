"""
hr_contracts/api/config.py

HR07-02 模板与规则 CRUD API + governance（07 总册 §83）。
"""

from __future__ import annotations

import json

from django.views.decorators.http import require_GET, require_POST

from hr_contracts.api.base import handle_hr07_error, make_hr07_context, ok
from hr_contracts.api.exceptions import NotFoundError
from hr_contracts.permissions import require_hr_contract_permission
from hr_contracts.services.template_governance import TemplateGovernanceService


def _ctx(request):
    return make_hr07_context(request)


def _actor(request):
    return request.user.id if request.user.is_authenticated else None


@require_GET
@require_hr_contract_permission("hr.contract.template.view")
def types_list(request):
    try:
        from hr_contracts.models import HrAgreementType
        items = list(
            HrAgreementType.objects.filter(tenant_id=_ctx(request).tenant_id).values(
                "id", "code", "name", "family", "term_mode", "active", "overlap_policy"
            )
        )
        return ok(request, {"items": [{"id": str(i.pop("id")), **i} for i in items]})
    except Exception as exc:
        return handle_hr07_error(request, exc)


@require_GET
@require_hr_contract_permission("hr.contract.template.view")
def templates_list(request):
    try:
        from hr_contracts.models import HrAgreementTemplate, HrAgreementTemplateVersion
        items = list(
            HrAgreementTemplate.objects.filter(tenant_id=_ctx(request).tenant_id).values(
                "id", "code", "name", "status", "agreement_type_id__name"
            )
        )
        for item in items:
            item["id"] = str(item.pop("id"))
            item["current_version"] = (
                HrAgreementTemplateVersion.objects.filter(
                    tenant_id=_ctx(request).tenant_id, template_id=item["id"], status="ACTIVE"
                )
                .values("version_no", "effective_from")
                .first()
            )
        return ok(request, {"items": items})
    except Exception as exc:
        return handle_hr07_error(request, exc)


@require_POST
@require_hr_contract_permission("hr.contract.template.manage")
def template_submit(request, template_id):
    try:
        data = TemplateGovernanceService(_ctx(request)).submit_for_review(template_id, actor=_actor(request))
        return ok(request, data)
    except Exception as exc:
        return handle_hr07_error(request, exc)


@require_POST
@require_hr_contract_permission("hr.contract.template.manage")
def template_publish(request, version_id):
    try:
        data = TemplateGovernanceService(_ctx(request)).publish(version_id, actor=_actor(request))
        return ok(request, data)
    except Exception as exc:
        return handle_hr07_error(request, exc)


@require_POST
@require_hr_contract_permission("hr.contract.template.manage")
def template_retire(request, template_id):
    try:
        data = TemplateGovernanceService(_ctx(request)).retire(template_id, actor=_actor(request))
        return ok(request, data)
    except Exception as exc:
        return handle_hr07_error(request, exc)


@require_POST
@require_hr_contract_permission("hr.contract.rule.manage")
def rules_evaluate(request):
    try:
        from hr_contracts.services.rule_service import RuleService
        body = json.loads(request.body or "{}")
        results = RuleService(_ctx(request).tenant_id).evaluate(
            agreement_type=None,
            proposed_start=body.get("proposedStart"),
            proposed_end=body.get("proposedEnd"),
        )
        return ok(request, {"rules": RuleService.to_json(results), "hasBlocker": RuleService.has_blocker(results)})
    except Exception as exc:
        return handle_hr07_error(request, exc)
