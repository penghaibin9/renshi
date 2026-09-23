from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login, logout
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from urllib.parse import urlencode
from django.views.decorators.http import require_http_methods

from .models import SsoLoginEvidence
from .sso_runtime import (
    SsoRuntimeError, begin_url, complete_callback, get_sso_connection,
    ldap_authenticate, record_evidence, resolve_identity, safe_next,
)


def _protocol(connection):
    return connection.adapter_code.replace("SSO_", "")


def _failure(request, connection, exc):
    record_evidence(connection, protocol=_protocol(connection), status=SsoLoginEvidence.Status.FAILED, code=exc.code, detail={"phase":"login","reason":exc.code})
    messages.error(request, f"统一认证登录失败：{exc}")
    return redirect("login")


def start(request, connection_id):
    try:
        connection = get_sso_connection(connection_id)
        if connection.adapter_code == "SSO_LDAP":
            target = reverse("hr-sso-ldap", kwargs={"connection_id": connection.pk})
            next_url = safe_next(request, request.GET.get("next"))
            return redirect(target + "?" + urlencode({"next": next_url}))
        return HttpResponseRedirect(begin_url(request, connection, next_url=request.GET.get("next", "/")))
    except SsoRuntimeError as exc:
        try: connection
        except UnboundLocalError: return redirect("login")
        return _failure(request, connection, exc)


def callback(request, connection_id):
    try:
        connection = get_sso_connection(connection_id)
        identity, next_url = complete_callback(request, connection)
        login(request, identity.user, backend="base.auth_backends.CompanyScopedBackend")
        request.session["selected_company"] = str(connection.tenant_id)
        request.session["hr_sso_connection_id"] = str(connection.pk)
        request.session["hr_sso_protocol"] = _protocol(connection)
        record_evidence(connection, protocol=_protocol(connection), status=SsoLoginEvidence.Status.SUCCESS, subject=identity.subject, staff_no=identity.staff_no, user_id=identity.user.pk, detail={"phase":"callback"})
        messages.success(request, "学校统一认证登录成功。")
        return redirect(next_url)
    except SsoRuntimeError as exc:
        try: connection
        except UnboundLocalError: return redirect("login")
        return _failure(request, connection, exc)


@require_http_methods(["GET", "POST"])
def ldap_login(request, connection_id):
    try: connection = get_sso_connection(connection_id)
    except SsoRuntimeError: return redirect("login")
    if connection.adapter_code != "SSO_LDAP": return redirect("login")
    next_url = safe_next(request, request.POST.get("next") if request.method=="POST" else request.GET.get("next"))
    if request.method == "POST":
        try:
            claims=ldap_authenticate(connection,username=request.POST.get("username"),password=request.POST.get("password"))
            identity=resolve_identity(connection,claims)
            login(request,identity.user,backend="base.auth_backends.CompanyScopedBackend")
            request.session["selected_company"]=str(connection.tenant_id);request.session["hr_sso_connection_id"]=str(connection.pk);request.session["hr_sso_protocol"]="LDAP"
            record_evidence(connection,protocol="LDAP",status=SsoLoginEvidence.Status.SUCCESS,subject=identity.subject,staff_no=identity.staff_no,user_id=identity.user.pk,detail={"phase":"ldap"})
            return redirect(next_url)
        except SsoRuntimeError as exc:
            record_evidence(connection,protocol="LDAP",status=SsoLoginEvidence.Status.FAILED,code=exc.code,detail={"phase":"ldap","reason":exc.code})
            messages.error(request,f"LDAP 登录失败：{exc}")
    return render(request,"hr_integration/sso_ldap_login.html",{"connection":connection,"next_url":next_url})


def sso_logout(request):
    connection_id=request.session.get("hr_sso_connection_id")
    connection=None
    if connection_id:
        try: connection=get_sso_connection(connection_id,enabled=False)
        except SsoRuntimeError: connection=None
    logout(request)
    if connection and connection.adapter_code == "SSO_CAS":
        path=str((connection.config_json or {}).get("logout_path") or "").strip()
        if path:
            from .sso_runtime import _join, _runtime_https_required
            url=_join(connection.base_url,path)
            try: _runtime_https_required(url); return HttpResponseRedirect(url)
            except SsoRuntimeError: pass
    return redirect("login")
