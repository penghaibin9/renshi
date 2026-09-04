"""Operational configuration and expiry workbench for canonical HR07."""

from __future__ import annotations

import re
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from hr_contracts.api.base import api_error, api_success, json_body, resolve_contract_tenant
from hr_contracts.models import (
    HrContractExpiryPolicy,
    HrContractExpiryRiskFact,
    HrContractTemplateVersion,
)
from hr_contracts.permissions import (
    PERM_AGREEMENT_CREATE,
    PERM_AGREEMENT_VIEW,
    enforce_contract_permission,
)
from hr_contracts.services.alert_escalation import (
    CanonicalContractExpiryService,
    ContractExpiryError,
)


def _actor_id(request):
    return getattr(getattr(request, "user", None), "id", None)


def _as_date(value, label, *, required=True):
    if value in (None, "") and not required:
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是有效日期") from exc


def _template_json(row):
    return {
        "id": str(row.id),
        "templateCode": row.template_code,
        "templateName": row.template_name,
        "agreementType": row.agreement_type,
        "versionNo": row.version_no,
        "bodyTemplate": row.body_template,
        "numberingRule": row.numbering_rule_json,
        "termRule": row.term_rule_json,
        "effectiveFrom": row.effective_from.isoformat(),
        "effectiveTo": row.effective_to.isoformat() if row.effective_to else None,
        "status": row.status,
        "contentHash": row.content_hash,
        "publishedAt": row.published_at.isoformat(),
    }


def _policy_json(row):
    return {
        "id": str(row.id),
        "policyVersion": row.policy_version,
        "agreementType": row.agreement_type,
        "warningDays": row.warning_days,
        "criticalAfterDays": row.critical_after_days,
        "actionType": row.action_type,
        "active": row.active,
        "contentHash": row.content_hash,
        "createdAt": row.created_at.isoformat(),
    }


def _risk_json(row):
    return {
        "id": str(row.id),
        "agreementId": str(row.agreement_id),
        "agreementNo": row.agreement.agreement_no,
        "agreementTitle": row.agreement.agreement_title,
        "caseId": str(row.action_case_id),
        "caseNo": row.action_case.case_no,
        "caseStatus": row.action_case.status,
        "riskStage": row.risk_stage,
        "severity": row.severity,
        "dueDate": row.due_date.isoformat(),
        "observedAsOf": row.observed_as_of.isoformat(),
        "daysToExpiry": row.days_to_expiry,
        "policyVersion": row.policy_version,
    }


def _handle(request, permission, operation):
    try:
        enforce_contract_permission(request, permission)
        tenant_id = resolve_contract_tenant(request)
        return operation(tenant_id)
    except PermissionDenied as exc:
        return api_error(request, "PERMISSION_DENIED", str(exc), status=403)
    except (TypeError, ValueError) as exc:
        return api_error(request, "INVALID_REQUEST", str(exc), status=400)
    except ValidationError as exc:
        return api_error(request, "INVALID_REQUEST", "; ".join(exc.messages), status=409)
    except IntegrityError:
        return api_error(
            request,
            "CONFIGURATION_CONFLICT",
            "配置已被其他操作更新，请刷新后重试",
            status=409,
        )
    except ContractExpiryError as exc:
        return api_error(request, exc.code, str(exc), status=409)


@require_GET
def setup_workbench(request):
    def operation(tenant_id):
        templates = HrContractTemplateVersion.objects.filter(
            tenant_id=tenant_id
        ).order_by("template_code", "-version_no")[:300]
        policies = HrContractExpiryPolicy.objects.filter(tenant_id=tenant_id).order_by(
            "agreement_type", "-created_at"
        )[:300]
        risks = HrContractExpiryRiskFact.objects.filter(tenant_id=tenant_id).select_related(
            "agreement", "action_case"
        ).order_by("-observed_as_of", "due_date", "agreement__agreement_no")[:500]
        return api_success(
            request,
            {
                "templates": [_template_json(row) for row in templates],
                "expiryPolicies": [_policy_json(row) for row in policies],
                "expiryRisks": [_risk_json(row) for row in risks],
            },
        )

    return _handle(request, PERM_AGREEMENT_VIEW, operation)


@require_POST
def publish_template(request):
    def operation(tenant_id):
        payload = json_body(request)
        code = str(payload.get("templateCode") or "").strip().upper()
        name = str(payload.get("templateName") or "").strip()
        agreement_type = str(payload.get("agreementType") or "").strip().upper()
        body_template = str(payload.get("bodyTemplate") or "").strip()
        if not re.fullmatch(r"[A-Z0-9_-]{2,64}", code):
            raise ValueError("模板代码只能包含大写字母、数字、下划线和短横线")
        if not name or not agreement_type or not body_template:
            raise ValueError("模板名称、合同类型和正文模板不能为空")
        effective_from = _as_date(payload.get("effectiveFrom"), "生效日期")
        effective_to = _as_date(payload.get("effectiveTo"), "失效日期", required=False)
        if effective_to and effective_to <= effective_from:
            raise ValueError("失效日期必须晚于生效日期")
        prefix = str(payload.get("numberingPrefix") or code).strip().upper()
        if not re.fullmatch(r"[A-Z0-9_-]{1,32}", prefix):
            raise ValueError("编号前缀格式无效")
        try:
            term_months = int(payload.get("defaultTermMonths") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("默认期限月数无效") from exc
        if term_months < 0 or term_months > 1200:
            raise ValueError("默认期限月数必须在 0 到 1200 之间")

        with transaction.atomic():
            current = HrContractTemplateVersion.objects.select_for_update().filter(
                tenant_id=tenant_id, template_code=code
            )
            version_no = (current.aggregate(value=Max("version_no"))["value"] or 0) + 1
            current.filter(status=HrContractTemplateVersion.Status.PUBLISHED).update(
                status=HrContractTemplateVersion.Status.RETIRED
            )
            row = HrContractTemplateVersion.objects.create(
                tenant_id=tenant_id,
                template_code=code,
                template_name=name[:160],
                agreement_type=agreement_type[:50],
                version_no=version_no,
                body_template=body_template,
                numbering_rule_json={"prefix": prefix, "pattern": f"{prefix}-{{YYYY}}-{{SEQ}}"},
                term_rule_json={"defaultTermMonths": term_months},
                effective_from=effective_from,
                effective_to=effective_to,
                published_by=_actor_id(request),
                created_by=_actor_id(request),
                updated_by=_actor_id(request),
            )
        return api_success(request, {"template": _template_json(row)}, status=201)

    return _handle(request, PERM_AGREEMENT_CREATE, operation)


@require_POST
def publish_expiry_policy(request):
    def operation(tenant_id):
        payload = json_body(request)
        agreement_type = str(payload.get("agreementType") or "").strip().upper()
        try:
            warning_days = int(payload.get("warningDays"))
            critical_after_days = int(payload.get("criticalAfterDays") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("预警天数必须是整数") from exc
        action_type = str(payload.get("actionType") or "").strip().upper()
        if warning_days < 1 or warning_days > 730:
            raise ValueError("提前预警天数必须在 1 到 730 之间")
        if critical_after_days < 0 or critical_after_days > 730:
            raise ValueError("严重逾期天数必须在 0 到 730 之间")
        if action_type not in HrContractExpiryPolicy.ActionType.values:
            raise ValueError("到期处置类型无效")
        policy_version = str(payload.get("policyVersion") or "").strip()
        if not policy_version:
            policy_version = f"EXP-{timezone.localdate():%Y%m%d}-{agreement_type or 'DEFAULT'}"
        if len(policy_version) > 64:
            raise ValueError("策略版本号过长")

        with transaction.atomic():
            HrContractExpiryPolicy.objects.select_for_update().filter(
                tenant_id=tenant_id, agreement_type=agreement_type, active=True
            ).update(active=False)
            row = HrContractExpiryPolicy.objects.create(
                tenant_id=tenant_id,
                policy_version=policy_version,
                agreement_type=agreement_type,
                warning_days=warning_days,
                critical_after_days=critical_after_days,
                action_type=action_type,
                active=True,
                created_by=_actor_id(request),
                updated_by=_actor_id(request),
            )
        return api_success(request, {"expiryPolicy": _policy_json(row)}, status=201)

    return _handle(request, PERM_AGREEMENT_CREATE, operation)


@require_POST
def scan_expiry(request):
    def operation(tenant_id):
        payload = json_body(request)
        as_of = _as_date(payload.get("asOf"), "扫描业务日期")
        dry_run = bool(payload.get("dryRun", False))
        result = CanonicalContractExpiryService(
            tenant_id=tenant_id, actor_user_id=_actor_id(request)
        ).scan(as_of=as_of, dry_run=dry_run)
        return api_success(request, {"scan": result})

    return _handle(request, PERM_AGREEMENT_CREATE, operation)
