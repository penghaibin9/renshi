from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from base.first_use import resolve_admin_school
from .adapters import AdapterError, catalog, get_spec
from .forms import ConnectionForm, FieldMappingForm, MappingProfileForm, SsoIdentityPrebindForm
from .models import (
    IntegrationAuditEvent,
    IntegrationConnection,
    IntegrationFieldMapping,
    IntegrationMappingProfile,
    SsoLoginEvidence,
)
from .services import IntegrationError, connection_contract, record_audit, save_connection, test_connection
from .sso_runtime import SsoRuntimeError, identity_binding_rows, prebind_identity
from .ui_catalog import adapter_ui_catalog, category_catalog, get_adapter_ui


def _tenant(request, permission):
    school = resolve_admin_school(request)
    if school is None:
        raise PermissionDenied("无法确认本校绑定，不会自动跨校选择。")
    if not request.user.is_superuser and not request.user.has_perm(permission):
        raise PermissionDenied(f"缺少权限: {permission}")
    return int(school.pk)


def _connection_form_initial(request):
    adapter_code = str(request.GET.get("adapter") or "").strip().upper()
    category = str(request.GET.get("category") or "").strip().upper()
    initial = {}
    if adapter_code:
        try:
            spec = get_spec(adapter_code)
            ui = get_adapter_ui(adapter_code)
            initial.update(
                adapter_code=spec.code,
                category=spec.category,
                code=spec.code,
                name=ui.get("title") or spec.name,
                enabled=False,
            )
        except AdapterError:
            pass
    elif category in dict(IntegrationConnection.Category.choices):
        initial["category"] = category
    return initial


def _save_connection_from_form(*, request, tenant_id, form, instance=None):
    cd = form.cleaned_data
    return save_connection(
        tenant_id=tenant_id,
        actor_user_id=request.user.pk,
        instance=instance,
        code=cd["code"],
        name=cd["name"],
        category=cd["category"],
        adapter_code=cd["adapter_code"],
        base_url=cd["base_url"],
        enabled=cd["enabled"],
        config=cd["config_text"],
        secrets=cd["credential_text"],
    )


def _hub_summary(connections):
    items = list(connections)
    total = len(items)
    verified = sum(1 for x in items if x.status == IntegrationConnection.Status.VERIFIED)
    error = sum(1 for x in items if x.status == IntegrationConnection.Status.ERROR)
    enabled = sum(1 for x in items if x.enabled)
    sso = [x for x in items if x.category == IntegrationConnection.Category.SSO]
    sso_state = "未配置"
    if any(x.status == IntegrationConnection.Status.VERIFIED for x in sso):
        sso_state = "已验证"
    elif any(x.status == IntegrationConnection.Status.ERROR for x in sso):
        sso_state = "有异常"
    elif sso:
        sso_state = "待验证"
    by_category = []
    for meta in category_catalog():
        rows = [x for x in items if x.category == meta["code"]]
        if any(x.status == IntegrationConnection.Status.ERROR for x in rows):
            state = "ERROR"
        elif any(x.status == IntegrationConnection.Status.VERIFIED for x in rows):
            state = "VERIFIED"
        elif rows:
            state = "CONFIGURED"
        else:
            state = "EMPTY"
        by_category.append({**meta, "count": len(rows), "state": state})
    return {
        "total": total,
        "verified": verified,
        "error": error,
        "enabled": enabled,
        "sso_state": sso_state,
        "categories": by_category,
    }


def _test_status_label(value):
    labels = {
        "VERIFIED": "连通已验证",
        "CONFIG_VALIDATED": "配置校验通过",
        "ERROR": "验证失败",
        "HOST_NOT_ALLOWED": "主机未授权",
        "NETWORK_ERROR": "网络连接失败",
        "PROBE_FAILED": "验证失败",
    }
    return labels.get(str(value or "").strip(), str(value or "尚未测试").strip() or "尚未测试")


def _connection_progress(obj):
    try:
        spec = get_spec(obj.adapter_code)
        credential_ready = (not spec.required_secret) or obj.has_credentials
    except AdapterError:
        credential_ready = False
    mapping_ready = obj.mapping_profiles.filter(enabled=True).exists()
    test_ready = obj.last_test_status in {"VERIFIED", "CONFIG_VALIDATED"}
    runtime_ready = True if obj.category != IntegrationConnection.Category.SSO else obj.sso_login_evidence.filter(status=SsoLoginEvidence.Status.SUCCESS).exists()
    steps = [
        {"key": "basic", "label": "基础连接", "done": bool(obj.code and obj.adapter_code)},
        {"key": "protocol", "label": "协议参数", "done": bool(obj.config_json)},
        {"key": "credential", "label": "密钥", "done": credential_ready},
        {"key": "mapping", "label": "字段映射", "done": mapping_ready},
        {"key": "verify", "label": "测试 / 启用", "done": bool(test_ready and obj.enabled)},
        {"key": "runtime", "label": "真实登录", "done": bool(runtime_ready and obj.enabled)},
    ]
    complete = sum(1 for x in steps if x["done"])
    return {"steps": steps, "complete": complete, "total": len(steps), "percent": int(complete / len(steps) * 100)}


@login_required
def hub(request):
    tenant_id = _tenant(request, "hr.integration.view")
    can_manage = request.user.is_superuser or request.user.has_perm("hr.integration.manage")
    can_test = request.user.is_superuser or request.user.has_perm("hr.integration.test")
    # Retain the V1 POST contract for old bookmarks/automation, while the V1.2 UI
    # uses a dedicated create page.
    form = ConnectionForm(tenant_id=tenant_id)
    if request.method == "POST":
        _tenant(request, "hr.integration.manage")
        form = ConnectionForm(request.POST, tenant_id=tenant_id)
        if form.is_valid():
            try:
                obj = _save_connection_from_form(request=request, tenant_id=tenant_id, form=form)
                messages.success(request, "接口连接已保存；密钥不会在页面回显。")
                return redirect("hr-integration-connection", connection_id=obj.pk)
            except (IntegrationError, IntegrityError) as exc:
                form.add_error(None, str(exc))
    connections = list(IntegrationConnection.objects.filter(tenant_id=tenant_id).order_by("category", "code"))
    return render(
        request,
        "hr_integration/hub.html",
        {
            "tenant_id": tenant_id,
            "connections": connections,
            "adapter_catalog": catalog(),
            "adapter_ui_catalog": adapter_ui_catalog(),
            "category_catalog": category_catalog(),
            "summary": _hub_summary(connections),
            "form": form,
            "can_manage": can_manage,
            "can_test": can_test,
        },
    )


@login_required
def connection_create(request):
    tenant_id = _tenant(request, "hr.integration.manage")
    form = ConnectionForm(tenant_id=tenant_id, initial=_connection_form_initial(request))
    if request.method == "POST":
        form = ConnectionForm(request.POST, tenant_id=tenant_id)
        if form.is_valid():
            try:
                obj = _save_connection_from_form(request=request, tenant_id=tenant_id, form=form)
                messages.success(request, "学校接口已创建。下一步维护字段映射并执行连通性测试。")
                return redirect("hr-integration-connection", connection_id=obj.pk)
            except (IntegrationError, IntegrityError) as exc:
                form.add_error(None, str(exc))
    return render(
        request,
        "hr_integration/connection_create.html",
        {
            "form": form,
            "tenant_id": tenant_id,
            "adapter_ui_catalog": adapter_ui_catalog(),
            "category_catalog": category_catalog(),
            "is_create": True,
        },
    )


@login_required
def connection_detail(request, connection_id):
    tenant_id = _tenant(request, "hr.integration.view")
    obj = get_object_or_404(IntegrationConnection, pk=connection_id, tenant_id=tenant_id)
    can_manage = request.user.is_superuser or request.user.has_perm("hr.integration.manage")
    can_test = request.user.is_superuser or request.user.has_perm("hr.integration.test")
    form = ConnectionForm(instance=obj, tenant_id=tenant_id)
    profile_form = MappingProfileForm(prefix="profile", tenant_id=tenant_id, connection=obj)
    prebind_form = SsoIdentityPrebindForm(prefix="prebind")
    if request.method == "POST":
        _tenant(request, "hr.integration.manage")
        action = request.POST.get("action")
        if action == "save_connection":
            form = ConnectionForm(request.POST, instance=obj, tenant_id=tenant_id)
            if form.is_valid():
                try:
                    _save_connection_from_form(request=request, tenant_id=tenant_id, form=form, instance=obj)
                    messages.success(request, "连接配置已更新。")
                    return redirect("hr-integration-connection", connection_id=obj.pk)
                except IntegrationError as exc:
                    form.add_error(None, str(exc))
        elif action == "prebind_identity" and obj.category == IntegrationConnection.Category.SSO:
            prebind_form = SsoIdentityPrebindForm(request.POST, prefix="prebind")
            if prebind_form.is_valid():
                try:
                    prebind_identity(obj, staff_no=prebind_form.cleaned_data["staff_no"], external_subject=prebind_form.cleaned_data["external_subject"], actor_user_id=request.user.pk)
                    messages.success(request, "统一认证身份已预绑定；Subject 原值不会在页面或审计日志回显。")
                    return redirect("hr-integration-connection", connection_id=obj.pk)
                except SsoRuntimeError as exc:
                    prebind_form.add_error(None, str(exc))
        elif action == "add_profile":
            profile_form = MappingProfileForm(request.POST, prefix="profile", tenant_id=tenant_id, connection=obj)
            if profile_form.is_valid():
                p = profile_form.save(commit=False)
                p.connection = obj
                p.tenant_id = tenant_id
                p.created_by = request.user.pk
                p.updated_by = request.user.pk
                try:
                    p.full_clean()
                    p.save()
                    record_audit(
                        tenant_id=tenant_id,
                        actor_user_id=request.user.pk,
                        event_type="MAPPING_PROFILE_CREATED",
                        connection_code=obj.code,
                        summary=f"创建映射方案 {p.code}",
                        payload={"profileCode": p.code, "direction": p.direction, "targetDomain": p.target_domain},
                    )
                    messages.success(request, "字段映射方案已创建。")
                    return redirect("hr-integration-connection", connection_id=obj.pk)
                except (ValidationError, IntegrityError) as exc:
                    profile_form.add_error(None, str(exc))
    obj.refresh_from_db()
    ui = get_adapter_ui(obj.adapter_code)
    test_runs = list(obj.test_runs.order_by("-tested_at")[:10])
    for run in test_runs:
        run.display_status = _test_status_label(run.status)
    return render(
        request,
        "hr_integration/connection_detail.html",
        {
            "connection": obj,
            "form": form,
            "profile_form": profile_form,
            "prebind_form": prebind_form,
            "identity_bindings": identity_binding_rows(obj) if obj.category == IntegrationConnection.Category.SSO else [],
            "profiles": obj.mapping_profiles.all().prefetch_related("fields"),
            "test_runs": test_runs,
            "last_test_label": _test_status_label(obj.last_test_status),
            "audit_events": IntegrationAuditEvent.objects.filter(tenant_id=tenant_id, connection_code=obj.code).order_by("-created_at")[:10],
            "can_manage": can_manage,
            "can_test": can_test,
            "adapter_ui": ui,
            "adapter_ui_catalog": adapter_ui_catalog(),
            "category_catalog": category_catalog(),
            "progress": _connection_progress(obj),
            "sso_evidence": obj.sso_login_evidence.order_by("-happened_at")[:10] if obj.category == IntegrationConnection.Category.SSO else [],
            "sso_success_count": obj.sso_login_evidence.filter(status=SsoLoginEvidence.Status.SUCCESS).count() if obj.category == IntegrationConnection.Category.SSO else 0,
            "is_create": False,
        },
    )


@login_required
def profile_detail(request, connection_id, profile_id):
    tenant_id = _tenant(request, "hr.integration.manage")
    connection = get_object_or_404(IntegrationConnection, pk=connection_id, tenant_id=tenant_id)
    profile = get_object_or_404(IntegrationMappingProfile, pk=profile_id, tenant_id=tenant_id, connection=connection)
    form = FieldMappingForm(request.POST or None, tenant_id=tenant_id, profile=profile)
    if request.method == "POST" and form.is_valid():
        row = form.save(commit=False)
        row.profile = profile
        row.tenant_id = tenant_id
        row.created_by = request.user.pk
        row.updated_by = request.user.pk
        try:
            row.full_clean()
            row.save()
            record_audit(
                tenant_id=tenant_id,
                actor_user_id=request.user.pk,
                event_type="FIELD_MAPPING_CREATED",
                connection_code=connection.code,
                summary=f"新增字段映射 {row.source_field} → {row.target_field}",
                payload={"profileCode": profile.code, "source": row.source_field, "target": row.target_field, "transform": row.transform_code},
            )
            messages.success(request, "字段映射已保存。")
            return redirect("hr-integration-profile", connection_id=connection.pk, profile_id=profile.pk)
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, str(exc))
    return render(
        request,
        "hr_integration/profile_detail.html",
        {
            "connection": connection,
            "profile": profile,
            "rows": profile.fields.all(),
            "form": form,
            "adapter_ui": get_adapter_ui(connection.adapter_code),
        },
    )


@login_required
@require_POST
def field_mapping_delete(request, connection_id, profile_id, field_id):
    tenant_id = _tenant(request, "hr.integration.manage")
    connection = get_object_or_404(IntegrationConnection, pk=connection_id, tenant_id=tenant_id)
    profile = get_object_or_404(IntegrationMappingProfile, pk=profile_id, tenant_id=tenant_id, connection=connection)
    row = get_object_or_404(IntegrationFieldMapping, pk=field_id, tenant_id=tenant_id, profile=profile)
    record_audit(
        tenant_id=tenant_id,
        actor_user_id=request.user.pk,
        event_type="FIELD_MAPPING_DELETED",
        connection_code=connection.code,
        summary=f"删除字段映射 {row.source_field} → {row.target_field}",
        payload={"profileCode": profile.code, "source": row.source_field, "target": row.target_field},
    )
    row.delete()
    messages.success(request, "字段映射已删除。")
    return redirect("hr-integration-profile", connection_id=connection.pk, profile_id=profile.pk)


@login_required
@require_POST
def mapping_profile_delete(request, connection_id, profile_id):
    tenant_id = _tenant(request, "hr.integration.manage")
    connection = get_object_or_404(IntegrationConnection, pk=connection_id, tenant_id=tenant_id)
    profile = get_object_or_404(IntegrationMappingProfile, pk=profile_id, tenant_id=tenant_id, connection=connection)
    record_audit(
        tenant_id=tenant_id,
        actor_user_id=request.user.pk,
        event_type="MAPPING_PROFILE_DELETED",
        connection_code=connection.code,
        summary=f"删除映射方案 {profile.code}",
        payload={"profileCode": profile.code, "fieldCount": profile.fields.count()},
    )
    profile.delete()
    messages.success(request, "映射方案已删除。")
    return redirect("hr-integration-connection", connection_id=connection.pk)


@login_required
@require_POST
def run_test(request, connection_id):
    tenant_id = _tenant(request, "hr.integration.test")
    status, _ = test_connection(connection_id=connection_id, tenant_id=tenant_id, actor_user_id=request.user.pk)
    if status in {"VERIFIED", "CONFIG_VALIDATED"}:
        messages.success(request, "接口测试完成：" + status)
    else:
        messages.error(request, "接口测试失败，查看最近测试记录。")
    return redirect("hr-integration-connection", connection_id=connection_id)


@login_required
def contract_api(request, connection_id):
    tenant_id = _tenant(request, "hr.integration.view")
    obj = get_object_or_404(IntegrationConnection, pk=connection_id, tenant_id=tenant_id)
    data = connection_contract(tenant_id=tenant_id, category=obj.category, code=obj.code)
    if not data:
        return JsonResponse({"error": {"code": "CONNECTION_NOT_ACTIVE"}}, status=404)
    response = JsonResponse({"data": data})
    response["Cache-Control"] = "no-store"
    return response
