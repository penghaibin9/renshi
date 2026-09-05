"""School-scoped setup entry; HR02/HR03 remain the business authorities.

This page reports observed configuration, not production readiness. GET never
creates defaults or marks steps complete. Profile writes use an actor/school
bound snapshot token, a MySQL row lock and an audit entry in one transaction.
"""

from __future__ import annotations

import hashlib
import json

from auditlog.models import LogEntry
from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from base.models import Company, CompanyGroupAssignment
from base.settings_center import _selected_company

PROFILE_FIELDS = ("company", "address", "country", "state", "city", "zip")
PROFILE_TOKEN_SALT = "base.school-management.profile.v1"
PROFILE_TOKEN_MAX_AGE = 1800


def profile_values(company):
    return {field: str(getattr(company, field, "") or "") for field in PROFILE_FIELDS}


def profile_fingerprint(values):
    canonical = json.dumps(
        {field: str(values.get(field) or "") for field in PROFILE_FIELDS},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def profile_complete(values):
    return all(str(values.get(field) or "").strip() for field in PROFILE_FIELDS)


def _profile_token(request, company):
    return signing.dumps(
        {
            "school": company.pk,
            "actor": request.user.pk,
            "fingerprint": profile_fingerprint(profile_values(company)),
        },
        salt=PROFILE_TOKEN_SALT,
    )


def _token_matches(request, company):
    try:
        snapshot = signing.loads(
            request.POST.get("profile_token", ""),
            salt=PROFILE_TOKEN_SALT,
            max_age=PROFILE_TOKEN_MAX_AGE,
        )
    except signing.BadSignature:
        return False
    return isinstance(snapshot, dict) and snapshot == {
        "school": company.pk,
        "actor": request.user.pk,
        "fingerprint": profile_fingerprint(profile_values(company)),
    }


class SchoolProfileForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = PROFILE_FIELDS
        labels = {
            "company": "学校名称",
            "address": "学校地址",
            "country": "国家/地区代码",
            "state": "省份",
            "city": "城市",
            "zip": "邮政编码",
        }
        help_texts = {"country": "中国填写 CN。"}

    def clean(self):
        cleaned = super().clean()
        for field in PROFILE_FIELDS:
            value = str(cleaned.get(field) or "").strip()
            if not value and field not in self.errors:
                self.add_error(field, "请填写此项后保存学校资料。")
            elif field in cleaned:
                cleaned[field] = value
        return cleaned


def _school(request):
    # Membership is checked even for historical school superusers. Platform
    # operators need an active elevation; request body never selects a school.
    company = _selected_company(request)
    if not request.user.has_perm("base.view_company"):
        raise PermissionDenied
    return Company.objects.get(pk=company.pk)


def _count_fact(request, company, *, key, title, permission, app, model, route, help_text):
    if not request.user.has_perm(permission):
        return {"key": key, "title": title, "state": "NO_ACCESS", "count": None,
                "url": None, "detail": "当前账号没有此项查看权限，请由学校授权负责人处理。"}
    try:
        count = apps.get_model(app, model).objects.filter(tenant_id=company.pk).count()
    except (LookupError, DatabaseError):
        # Unavailable is not the same as an empty school, and never turns green.
        return {"key": key, "title": title, "state": "UNAVAILABLE", "count": None,
                "url": reverse(route), "detail": "暂时无法读取配置，请检查服务后重新核验。"}
    return {"key": key, "title": title, "state": "RECORDED" if count else "MISSING",
            "count": count, "url": reverse(route), "detail": help_text}


def setup_summary(request, company):
    steps = [{
        "key": "profile", "title": "学校资料", "count": None, "url": "#school-profile",
        "state": "RECORDED" if profile_complete(profile_values(company)) else "MISSING",
        "detail": "填写学校名称和地址信息。学校编号与平台归属不允许在这里修改。",
    }]
    specifications = (
        ("organizations", "组织机构", "hr.structure.organization.view", "hr_structure",
         "HrOrganization", "hr-structure-organizations", "在 HR02 建立组织并确认生效状态，不重复创建旧部门。"),
        ("positions", "岗位与编制", "hr.structure.position.view", "hr_structure",
         "HrPosition", "hr-structure-positions", "在 HR02 配置岗位与编制；已有记录不代表已经审批生效。"),
        ("staff", "教职工主档", "hr.staff.view", "hr_staff", "HrStaffMaster",
         "hr03-staff-list", "通过 HR03 建档或导入，再核对工号、任职与账号关联。"),
    )
    for key, title, permission, app, model, route, help_text in specifications:
        steps.append(_count_fact(request, company, key=key, title=title, permission=permission,
                                 app=app, model=model, route=route, help_text=help_text))
    # This is a narrowly defined account observation, NOT a role-completeness
    # claim. Do not count a global superuser as a deliverable school admin.
    try:
        admin_present = CompanyGroupAssignment.objects.filter(
            company_id=company.pk, user__is_active=True, user__is_superuser=False,
            group__permissions__content_type__app_label="base",
            group__permissions__codename="change_company",
        ).exists()
        admin_state = "RECORDED" if admin_present else "MISSING"
    except DatabaseError:
        admin_state = "UNAVAILABLE"
    steps.append({
        "key": "school_admin", "title": "学校管理账号", "state": admin_state,
        "count": None, "url": None,
        "detail": "核验本校是否存在已授权的普通管理账号；历史超级管理员不计入此项。完整角色与审批负责人仍须验收。",
    })
    return {
        "schoolId": str(company.pk), "schoolName": company.company, "steps": steps,
        "state": "CONFIGURATION_REVIEW_REQUIRED", "productionReady": False,
        "recorded": sum(step["state"] == "RECORDED" for step in steps),
        "total": len(steps),
    }


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def school_management(request):
    company = _school(request)
    can_edit = request.user.has_perm("base.change_company")
    form = SchoolProfileForm(instance=company)
    status = 200
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        with transaction.atomic():
            company = Company.objects.select_for_update().get(pk=company.pk)
            if not _token_matches(request, company):
                form = SchoolProfileForm(profile_values(company), instance=company)
                form.is_valid()
                form.add_error(None, "资料已更新或编辑凭证已过期。已显示当前资料，请核对后重新保存。")
                status = 409
            else:
                before = profile_values(company)
                form = SchoolProfileForm(request.POST, instance=company)
                if form.is_valid():
                    company = form.save()
                    after = profile_values(company)
                    changes = {key: [before[key], after[key]] for key in PROFILE_FIELDS
                               if before[key] != after[key]}
                    if changes:
                        LogEntry.objects.log_create(
                            company, action=LogEntry.Action.UPDATE, changes=changes,
                            actor=request.user,
                            additional_data={"tenant_id": company.pk,
                                             "source": "school_management"},
                        )
                else:
                    status = 400
        if status != 200:
            # ModelForm validation mutates its instance even on invalid input.
            # Sign and report persisted data, not a failed form's in-memory values.
            company = Company.objects.get(pk=company.pk)
        if status == 200:
            # Update the display cache only. It is never an authorization source.
            cached = dict(request.session.get("selected_company_instance") or {})
            cached["company"] = company.company
            request.session["selected_company_instance"] = cached
            messages.success(request, "学校资料已保存。")
            return redirect("school-management")
    if not can_edit:
        for field in form.fields.values():
            field.disabled = True
    return render(request, "base/settings/school_management.html", {
        "school": company, "profile_form": form, "can_edit_profile": can_edit,
        "profile_token": _profile_token(request, company),
        "setup": setup_summary(request, company),
    }, status=status)


@login_required
@never_cache
@require_GET
def school_setup_status(request):
    company = _school(request)
    summary = setup_summary(request, company)
    unavailable = any(step["state"] == "UNAVAILABLE" for step in summary["steps"])
    return JsonResponse(summary, status=503 if unavailable else 200)
