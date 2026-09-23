from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from base.first_use import resolve_admin_school

from .forms import (
    ApprovalRoleForm, ConditionRuleForm, ExcelColumnForm, ExcelTemplateForm,
    FieldDefinitionForm, FormDefinitionForm, NotificationRuleForm, PrintTemplateForm,
    StageForm, WorkflowCreateForm,
)
from .models import (
    ApprovalRoleRule, ConditionRule, ExcelColumn, ExcelTemplate, FieldDefinition,
    FormDefinition, NotificationRule, PrintTemplate, WorkflowDefinition, WorkflowStage,
    WorkflowVersion, ConfigurationAuditEvent,
)
from .services import (
    ConfigurationError, clone_to_draft, create_workflow, get_draft,
    get_published_version, publish, snapshot, validate_for_publish,
)


def _tenant(request, permission):
    if not getattr(request.user, "is_authenticated", False): raise PermissionDenied
    school = resolve_admin_school(request)
    if school is None: raise PermissionDenied("无法确认本校绑定，不会自动跨校选择。")
    if not request.user.is_superuser and not request.user.has_perm(permission):
        raise PermissionDenied(f"缺少权限: {permission}")
    return int(school.pk)



def _audit_component(request, tenant_id, event_type, kind, obj, workflow):
    ConfigurationAuditEvent.objects.create(
        tenant_id=tenant_id, actor_user_id=request.user.pk, event_type=event_type,
        object_type=f"{kind}:{obj.__class__.__name__}", object_id=str(obj.pk),
        summary=f"{event_type}: {workflow.code}/{kind}", payload_json={"workflowCode": workflow.code},
    )

def _workflow(tenant_id, workflow_id):
    return get_object_or_404(WorkflowDefinition, pk=workflow_id, tenant_id=tenant_id)


@login_required
def configuration_center(request):
    tenant_id = _tenant(request, "hr.configuration.view")
    can_manage = request.user.is_superuser or request.user.has_perm("hr.configuration.manage")
    if request.method == "POST":
        _tenant(request, "hr.configuration.manage")
        form = WorkflowCreateForm(request.POST)
        if form.is_valid():
            try:
                workflow, _ = create_workflow(tenant_id=tenant_id, actor_user_id=request.user.pk, **form.cleaned_data)
                messages.success(request, "流程配置已创建，请继续配置 8 个环节。")
                return redirect("hr-configuration-workflow", workflow_id=workflow.pk)
            except (ConfigurationError, IntegrityError) as exc:
                form.add_error(None, str(exc))
    else:
        form = WorkflowCreateForm()
    workflows = list(WorkflowDefinition.objects.filter(tenant_id=tenant_id).order_by("business_domain", "code"))
    rows=[]
    for item in workflows:
        draft=get_draft(item); published=get_published_version(item)
        rows.append({"workflow":item,"draft":draft,"published":published})
    return render(request,"hr_configuration/config_center.html",{"tenant_id":tenant_id,"rows":rows,"create_form":form,"can_manage":can_manage})


_FORM_REGISTRY = {
    "stage": (WorkflowStage, StageForm),
    "form": (FormDefinition, FormDefinitionForm),
    "field": (FieldDefinition, FieldDefinitionForm),
    "approval": (ApprovalRoleRule, ApprovalRoleForm),
    "condition": (ConditionRule, ConditionRuleForm),
    "notification": (NotificationRule, NotificationRuleForm),
    "print": (PrintTemplate, PrintTemplateForm),
    "excel": (ExcelTemplate, ExcelTemplateForm),
    "excel_column": (ExcelColumn, ExcelColumnForm),
}


def _forms(version, data=None):
    return {kind: cls(data if data and data.get("action") == f"add_{kind}" else None, version=version, prefix=kind) for kind,(_,cls) in _FORM_REGISTRY.items()}


@login_required
def workflow_detail(request, workflow_id):
    tenant_id=_tenant(request,"hr.configuration.view")
    workflow=_workflow(tenant_id,workflow_id)
    draft=get_draft(workflow); published=get_published_version(workflow)
    can_manage=request.user.is_superuser or request.user.has_perm("hr.configuration.manage")
    can_publish=request.user.is_superuser or request.user.has_perm("hr.configuration.publish")
    if request.method=="POST":
        if request.POST.get("action")=="clone":
            _tenant(request,"hr.configuration.manage")
            draft=clone_to_draft(workflow_id=workflow.pk,tenant_id=tenant_id,actor_user_id=request.user.pk)
            messages.success(request,f"已创建 v{draft.version_no} 草稿。")
            return redirect("hr-configuration-workflow",workflow_id=workflow.pk)
        if request.POST.get("action")=="publish":
            _tenant(request,"hr.configuration.publish")
            if not draft: raise PermissionDenied("没有可发布草稿")
            try:
                version=publish(version_id=draft.pk,tenant_id=tenant_id,actor_user_id=request.user.pk)
                messages.success(request,f"v{version.version_no} 已发布，历史版本保持不变。")
            except ConfigurationError as exc: messages.error(request,str(exc))
            return redirect("hr-configuration-workflow",workflow_id=workflow.pk)
        _tenant(request,"hr.configuration.manage")
        if not draft: raise PermissionDenied("请先创建新草稿")
        action=request.POST.get("action","")
        kind=action.removeprefix("add_") if action.startswith("add_") else ""
        if kind in _FORM_REGISTRY:
            _, form_cls=_FORM_REGISTRY[kind]
            form=form_cls(request.POST,version=draft,prefix=kind)
            if form.is_valid():
                obj=form.save(commit=False); obj.created_by=request.user.pk; obj.updated_by=request.user.pk; obj.full_clean(); obj.save()
                _audit_component(request, tenant_id, "CONFIG_COMPONENT_CREATED", kind, obj, workflow)
                messages.success(request,"已保存到草稿。")
                return redirect("hr-configuration-workflow",workflow_id=workflow.pk)
            forms=_forms(draft); forms[kind]=form
        else: forms=_forms(draft)
    else:
        forms=_forms(draft) if draft else {}
    version=draft or published
    context={"tenant_id":tenant_id,"workflow":workflow,"draft":draft,"published":published,"version":version,"forms":forms,"can_manage":can_manage,"can_publish":can_publish,"publish_errors":validate_for_publish(draft) if draft else []}
    if version:
        context.update({
            "stages":WorkflowStage.objects.filter(version=version),"form_defs":FormDefinition.objects.filter(version=version),
            "field_defs":FieldDefinition.objects.filter(version=version).select_related("form"),"approvals":ApprovalRoleRule.objects.filter(version=version),
            "conditions":ConditionRule.objects.filter(version=version),"notifications":NotificationRule.objects.filter(version=version),
            "print_templates":PrintTemplate.objects.filter(version=version),"excel_templates":ExcelTemplate.objects.filter(version=version).prefetch_related("columns"),
        })
    return render(request,"hr_configuration/workflow_detail.html",context)


@login_required
def component_edit(request, workflow_id, kind, object_id):
    tenant_id=_tenant(request,"hr.configuration.manage")
    workflow=_workflow(tenant_id,workflow_id); draft=get_draft(workflow)
    if not draft or kind not in _FORM_REGISTRY: raise PermissionDenied("只能修改当前草稿")
    model,form_cls=_FORM_REGISTRY[kind]
    obj=get_object_or_404(model,pk=object_id,tenant_id=tenant_id,version=draft)
    form=form_cls(request.POST or None,instance=obj,version=draft)
    if request.method=="POST" and form.is_valid():
        saved=form.save(commit=False); saved.updated_by=request.user.pk; saved.full_clean(); saved.save()
        _audit_component(request, tenant_id, "CONFIG_COMPONENT_UPDATED", kind, saved, workflow)
        messages.success(request,"草稿已更新。")
        return redirect("hr-configuration-workflow",workflow_id=workflow.pk)
    return render(request,"hr_configuration/component_edit.html",{"workflow":workflow,"kind":kind,"form":form})


@login_required
@require_POST
def component_delete(request, workflow_id, kind, object_id):
    tenant_id=_tenant(request,"hr.configuration.manage")
    workflow=_workflow(tenant_id,workflow_id); draft=get_draft(workflow)
    if not draft or kind not in _FORM_REGISTRY: raise PermissionDenied("只能删除草稿内容")
    model,_=_FORM_REGISTRY[kind]
    obj=get_object_or_404(model,pk=object_id,tenant_id=tenant_id,version=draft)
    _audit_component(request, tenant_id, "CONFIG_COMPONENT_DELETED", kind, obj, workflow)
    obj.delete(); messages.success(request,"已从草稿删除。")
    return redirect("hr-configuration-workflow",workflow_id=workflow.pk)


@login_required
def published_config_api(request, workflow_id):
    tenant_id=_tenant(request,"hr.configuration.view"); workflow=_workflow(tenant_id,workflow_id)
    version=get_published_version(workflow)
    if not version: return JsonResponse({"error":{"code":"NO_PUBLISHED_VERSION"}},status=404)
    data=snapshot(version); data["contentHash"]=version.content_hash
    response=JsonResponse({"data":data}); response["Cache-Control"]="no-store"; return response
