from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy

from django.db import transaction
from django.utils import timezone

from .models import (
    ApprovalRoleRule,
    ConditionRule,
    ConfigurationAuditEvent,
    ExcelColumn,
    ExcelTemplate,
    FieldDefinition,
    FormDefinition,
    NotificationRule,
    PrintTemplate,
    WorkflowDefinition,
    WorkflowStage,
    WorkflowVersion,
)

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
SUPPORTED_DOMAINS = ("HR04", "HR05", "HR06", "HR12", "HR13", "HR14", "HR16", "HR17")


class ConfigurationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _audit(*, tenant_id, actor_user_id, event_type, obj, summary, payload=None):
    ConfigurationAuditEvent.objects.create(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        object_type=obj.__class__.__name__,
        object_id=str(obj.pk),
        summary=summary[:255],
        payload_json=payload or {},
    )


def normalize_code(value: str) -> str:
    code = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if not _CODE_RE.fullmatch(code):
        raise ConfigurationError("INVALID_CODE", "编码必须以字母开头，只能包含大写字母、数字和下划线")
    return code


def create_workflow(*, tenant_id: int, actor_user_id: int | None, code: str, name: str, business_domain: str, description: str = ""):
    domain = str(business_domain or "").strip().upper()
    if domain not in SUPPORTED_DOMAINS:
        raise ConfigurationError("UNSUPPORTED_DOMAIN", f"V1 仅支持: {', '.join(SUPPORTED_DOMAINS)}")
    code = normalize_code(code)
    name = str(name or "").strip()
    if not name:
        raise ConfigurationError("NAME_REQUIRED", "流程名称不能为空")
    with transaction.atomic():
        workflow = WorkflowDefinition.objects.create(
            tenant_id=tenant_id,
            code=code,
            name=name,
            business_domain=domain,
            description=str(description or "").strip(),
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        version = WorkflowVersion.objects.create(
            tenant_id=tenant_id,
            workflow=workflow,
            version_no=1,
            status=WorkflowVersion.Status.DRAFT,
            change_note="初始草稿",
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        _audit(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            event_type="WORKFLOW_CREATED",
            obj=workflow,
            summary=f"创建流程 {workflow.code}",
            payload={"domain": domain, "versionId": str(version.id)},
        )
    return workflow, version


def get_draft(workflow: WorkflowDefinition) -> WorkflowVersion | None:
    return workflow.versions.filter(status=WorkflowVersion.Status.DRAFT).order_by("-version_no").first()


def get_published_version(workflow: WorkflowDefinition) -> WorkflowVersion | None:
    return workflow.versions.filter(status=WorkflowVersion.Status.PUBLISHED).order_by("-version_no", "-published_at").first()


def snapshot(version: WorkflowVersion) -> dict:
    excel_templates = []
    for template in ExcelTemplate.objects.filter(version=version).order_by("code"):
        excel_templates.append(
            {
                "code": template.code,
                "name": template.name,
                "direction": template.direction,
                "sheetName": template.sheet_name,
                "enabled": template.enabled,
                "columns": [
                    {
                        "fieldKey": col.field_key,
                        "header": col.header,
                        "sortOrder": col.sort_order,
                        "required": col.required,
                        "dataType": col.data_type,
                        "exampleValue": col.example_value,
                    }
                    for col in ExcelColumn.objects.filter(template=template).order_by("sort_order")
                ],
            }
        )
    return {
        "schemaVersion": "hr.configuration.v1",
        "workflow": {
            "code": version.workflow.code,
            "name": version.workflow.name,
            "businessDomain": version.workflow.business_domain,
            "versionNo": version.version_no,
        },
        "stages": [
            {"code": x.code, "name": x.name, "sortOrder": x.sort_order, "isStart": x.is_start, "isEnd": x.is_end}
            for x in WorkflowStage.objects.filter(version=version).order_by("sort_order")
        ],
        "forms": [
            {"code": x.code, "title": x.title, "stageCode": x.stage_code, "sortOrder": x.sort_order, "description": x.description}
            for x in FormDefinition.objects.filter(version=version).order_by("sort_order")
        ],
        "fields": [
            {
                "formCode": x.form.code, "key": x.key, "label": x.label, "fieldType": x.field_type,
                "required": x.required, "sortOrder": x.sort_order, "helpText": x.help_text,
                "defaultValue": x.default_value, "options": x.options_json or [], "validation": x.validation_json or {},
            }
            for x in FieldDefinition.objects.filter(version=version).select_related("form").order_by("form__sort_order", "sort_order")
        ],
        "approvalRoles": [
            {"code": x.code, "stageCode": x.stage_code, "roleCode": x.role_code, "roleName": x.role_name, "dataScope": x.data_scope, "sortOrder": x.sort_order, "approvalMode": x.approval_mode}
            for x in ApprovalRoleRule.objects.filter(version=version).order_by("sort_order", "code")
        ],
        "conditions": [
            {"code": x.code, "name": x.name, "sourceStageCode": x.source_stage_code, "fieldKey": x.field_key, "operator": x.operator, "compareValue": x.compare_value_json or {}, "targetStageCode": x.target_stage_code, "priority": x.priority}
            for x in ConditionRule.objects.filter(version=version).order_by("priority", "code")
        ],
        "notifications": [
            {"code": x.code, "eventCode": x.event_code, "channel": x.channel, "recipientRoleCode": x.recipient_role_code, "subjectTemplate": x.subject_template, "bodyTemplate": x.body_template, "enabled": x.enabled}
            for x in NotificationRule.objects.filter(version=version).order_by("code")
        ],
        "printTemplates": [
            {"code": x.code, "name": x.name, "outputFormat": x.output_format, "templateBody": x.template_body, "enabled": x.enabled}
            for x in PrintTemplate.objects.filter(version=version).order_by("code")
        ],
        "excelTemplates": excel_templates,
    }


def _snapshot_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_for_publish(version: WorkflowVersion) -> list[str]:
    errors: list[str] = []
    if version.status != WorkflowVersion.Status.DRAFT:
        errors.append("只能发布草稿版本")
        return errors
    stages = list(WorkflowStage.objects.filter(version=version).order_by("sort_order"))
    stage_codes = {x.code for x in stages}
    if len(stages) < 2:
        errors.append("流程至少需要 2 个阶段")
    if sum(1 for x in stages if x.is_start) != 1:
        errors.append("流程必须且只能有 1 个开始阶段")
    if not any(x.is_end for x in stages):
        errors.append("流程至少需要 1 个结束阶段")
    forms = list(FormDefinition.objects.filter(version=version))
    if not forms:
        errors.append("至少需要 1 张表单")
    for form in forms:
        if form.stage_code and form.stage_code not in stage_codes:
            errors.append(f"表单 {form.code} 引用了不存在的阶段 {form.stage_code}")
    field_keys = set(FieldDefinition.objects.filter(version=version).values_list("key", flat=True))
    for rule in ApprovalRoleRule.objects.filter(version=version):
        if rule.stage_code not in stage_codes:
            errors.append(f"审批角色 {rule.code} 引用了不存在的阶段 {rule.stage_code}")
    for rule in ConditionRule.objects.filter(version=version):
        if rule.source_stage_code not in stage_codes or rule.target_stage_code not in stage_codes:
            errors.append(f"条件 {rule.code} 的来源/目标阶段不存在")
        if rule.field_key not in field_keys:
            errors.append(f"条件 {rule.code} 引用了不存在的字段 {rule.field_key}")
    for template in ExcelTemplate.objects.filter(version=version, enabled=True):
        cols = list(ExcelColumn.objects.filter(template=template))
        if not cols:
            errors.append(f"Excel 模板 {template.code} 没有列")
        for col in cols:
            if col.field_key not in field_keys:
                errors.append(f"Excel 模板 {template.code} 引用了不存在字段 {col.field_key}")
    return errors


def publish(*, version_id, tenant_id: int, actor_user_id: int | None) -> WorkflowVersion:
    with transaction.atomic():
        version = (
            WorkflowVersion.objects.select_for_update()
            .select_related("workflow")
            .get(pk=version_id, tenant_id=tenant_id)
        )
        errors = validate_for_publish(version)
        if errors:
            raise ConfigurationError("PUBLISH_VALIDATION_FAILED", "；".join(errors))
        payload = snapshot(version)
        version.content_hash = _snapshot_hash(payload)
        version.status = WorkflowVersion.Status.PUBLISHED
        version.published_at = timezone.now()
        version.published_by = actor_user_id
        version.updated_by = actor_user_id
        version.save(update_fields=["content_hash", "status", "published_at", "published_by", "updated_by", "updated_at"])
        _audit(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            event_type="WORKFLOW_PUBLISHED",
            obj=version,
            summary=f"发布 {version.workflow.code} v{version.version_no}",
            payload={"contentHash": version.content_hash},
        )
        return version


def clone_to_draft(*, workflow_id, tenant_id: int, actor_user_id: int | None) -> WorkflowVersion:
    with transaction.atomic():
        workflow = WorkflowDefinition.objects.select_for_update().get(pk=workflow_id, tenant_id=tenant_id)
        existing = get_draft(workflow)
        if existing:
            return existing
        source = get_published_version(workflow)
        next_no = (workflow.versions.order_by("-version_no").values_list("version_no", flat=True).first() or 0) + 1
        target = WorkflowVersion.objects.create(
            tenant_id=tenant_id,
            workflow=workflow,
            version_no=next_no,
            status=WorkflowVersion.Status.DRAFT,
            change_note=f"从 v{source.version_no} 复制" if source else "新草稿",
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        if source:
            model_pairs = [
                (WorkflowStage, ["code", "name", "sort_order", "is_start", "is_end"]),
                (FormDefinition, ["code", "title", "stage_code", "sort_order", "description"]),
                (ApprovalRoleRule, ["code", "stage_code", "role_code", "role_name", "data_scope", "sort_order", "approval_mode"]),
                (ConditionRule, ["code", "name", "source_stage_code", "field_key", "operator", "compare_value_json", "target_stage_code", "priority"]),
                (NotificationRule, ["code", "event_code", "channel", "recipient_role_code", "subject_template", "body_template", "enabled"]),
                (PrintTemplate, ["code", "name", "output_format", "template_body", "enabled"]),
            ]
            forms_by_code = {}
            for row in FormDefinition.objects.filter(version=source).order_by("sort_order"):
                new = FormDefinition.objects.create(
                    tenant_id=tenant_id, version=target, code=row.code, title=row.title,
                    stage_code=row.stage_code, sort_order=row.sort_order, description=row.description,
                    created_by=actor_user_id, updated_by=actor_user_id,
                )
                forms_by_code[row.code] = new
            for row in FieldDefinition.objects.filter(version=source).select_related("form").order_by("sort_order"):
                FieldDefinition.objects.create(
                    tenant_id=tenant_id, version=target, form=forms_by_code[row.form.code],
                    key=row.key, label=row.label, field_type=row.field_type, required=row.required,
                    sort_order=row.sort_order, help_text=row.help_text, default_value=row.default_value,
                    options_json=deepcopy(row.options_json), validation_json=deepcopy(row.validation_json),
                    created_by=actor_user_id, updated_by=actor_user_id,
                )
            for model, fields in model_pairs:
                if model is FormDefinition:
                    continue
                for row in model.objects.filter(version=source):
                    values = {field: deepcopy(getattr(row, field)) for field in fields}
                    model.objects.create(tenant_id=tenant_id, version=target, created_by=actor_user_id, updated_by=actor_user_id, **values)
            for xls in ExcelTemplate.objects.filter(version=source):
                new_xls = ExcelTemplate.objects.create(
                    tenant_id=tenant_id, version=target, code=xls.code, name=xls.name,
                    direction=xls.direction, sheet_name=xls.sheet_name, enabled=xls.enabled,
                    created_by=actor_user_id, updated_by=actor_user_id,
                )
                for col in xls.columns.all():
                    ExcelColumn.objects.create(
                        tenant_id=tenant_id, version=target, template=new_xls,
                        field_key=col.field_key, header=col.header, sort_order=col.sort_order,
                        required=col.required, data_type=col.data_type, example_value=col.example_value,
                        created_by=actor_user_id, updated_by=actor_user_id,
                    )
        _audit(
            tenant_id=tenant_id, actor_user_id=actor_user_id, event_type="WORKFLOW_DRAFT_CLONED",
            obj=target, summary=f"创建 {workflow.code} v{next_no} 草稿",
        )
        return target


def get_published_workflow_config(*, tenant_id: int, business_domain: str, workflow_code: str | None = None) -> dict | None:
    qs = WorkflowDefinition.objects.filter(
        tenant_id=tenant_id,
        business_domain=str(business_domain).upper(),
        enabled=True,
    )
    if workflow_code:
        qs = qs.filter(code=str(workflow_code).upper())
    workflow = qs.order_by("code").first()
    if not workflow:
        return None
    version = get_published_version(workflow)
    if not version:
        return None
    payload = snapshot(version)
    if _snapshot_hash(payload) != version.content_hash:
        raise ConfigurationError("CONFIG_INTEGRITY_FAILED", "已发布配置完整性校验失败")
    payload["contentHash"] = version.content_hash
    return payload
