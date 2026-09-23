from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse
from xml.etree import ElementTree

import jwt
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .adapters import AdapterError, _require_allowed_host
from .crypto import decrypt_secret_payload
from .models import IntegrationConnection, SsoLoginEvidence


FLOW_SESSION_KEY = "hr_sso_flow_v1"
FLOW_TTL_SECONDS = 600
SUPPORTED = {"SSO_CAS", "SSO_OAUTH2", "SSO_OIDC", "SSO_LDAP"}


class SsoRuntimeError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400):
        self.code, self.status = code, status
        super().__init__(message)


def _bool(value, default=False):
    if value in (None, ""): return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def safe_next(request, value) -> str:
    value = str(value or "/").strip() or "/"
    if not url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return "/"
    return value


def _absolute(request, name: str, **kwargs):
    return request.build_absolute_uri(reverse(name, kwargs=kwargs))


def _runtime_https_required(url: str):
    parsed = urlparse(url)
    if not parsed.hostname:
        raise SsoRuntimeError("SSO_URL_INVALID", "统一认证地址无效")
    _require_allowed_host(parsed.hostname)
    allow_insecure = bool(getattr(settings, "HR_SSO_ALLOW_INSECURE_FOR_TESTS", False)) and bool(getattr(settings, "DEBUG", False))
    if parsed.scheme != "https" and not allow_insecure:
        raise SsoRuntimeError("SSO_HTTPS_REQUIRED", "统一认证运行时只允许 HTTPS")
    return parsed


def _join(base: str, path: str):
    return base.rstrip("/") + "/" + str(path or "").lstrip("/")


def _request(method: str, url: str, **kwargs):
    _runtime_https_required(url)
    timeout = float(getattr(settings, "HR_INTEGRATION_HTTP_TIMEOUT_SECONDS", 5) or 5)
    try:
        response = requests.request(method, url, timeout=timeout, allow_redirects=False, **kwargs)
    except requests.RequestException as exc:
        raise SsoRuntimeError("SSO_NETWORK_ERROR", "统一认证服务暂时不可达", status=502) from exc
    return response


def _secrets(connection: IntegrationConnection):
    try:
        return decrypt_secret_payload(connection.secret_ciphertext) if connection.secret_ciphertext else {}
    except Exception as exc:
        raise SsoRuntimeError("SSO_CREDENTIAL_DECRYPT_FAILED", "统一认证密钥无法解密，请管理员重新录入") from exc


def get_sso_connection(connection_id, *, tenant_id=None, enabled=True):
    qs = IntegrationConnection.objects.filter(pk=connection_id, category=IntegrationConnection.Category.SSO)
    if tenant_id is not None: qs = qs.filter(tenant_id=tenant_id)
    if enabled: qs = qs.filter(enabled=True)
    obj = qs.first()
    if not obj or obj.adapter_code not in SUPPORTED:
        raise SsoRuntimeError("SSO_CONNECTION_NOT_AVAILABLE", "统一认证连接不存在或尚未启用", status=404)
    return obj


def public_sso_connections():
    tenant = getattr(settings, "HR_SSO_PUBLIC_TENANT_ID", None)
    qs = IntegrationConnection.objects.filter(category="SSO", enabled=True, adapter_code__in=SUPPORTED).order_by("name", "code")
    if tenant not in (None, ""):
        try: return list(qs.filter(tenant_id=int(tenant)))
        except (TypeError, ValueError): return []
    tenants = list(qs.values_list("tenant_id", flat=True).distinct()[:2])
    return list(qs.filter(tenant_id=tenants[0])) if len(tenants) == 1 else []


def _flow(request, connection: IntegrationConnection, *, next_url="/", nonce="", verifier=""):
    state = secrets.token_urlsafe(32)
    data = {
        "state": state, "tenant_id": int(connection.tenant_id), "connection_id": str(connection.pk),
        "next": safe_next(request, next_url), "created": int(time.time()), "nonce": nonce, "verifier": verifier,
    }
    request.session[FLOW_SESSION_KEY] = data
    request.session.modified = True
    return data


def _consume_flow(request, connection, state):
    data = request.session.pop(FLOW_SESSION_KEY, None) or {}
    request.session.modified = True
    if not data or str(data.get("connection_id")) != str(connection.pk) or int(data.get("tenant_id") or 0) != int(connection.tenant_id):
        raise SsoRuntimeError("SSO_FLOW_MISSING", "统一认证登录流程已失效，请重新登录")
    if int(time.time()) - int(data.get("created") or 0) > FLOW_TTL_SECONDS:
        raise SsoRuntimeError("SSO_FLOW_EXPIRED", "统一认证登录流程已过期，请重新登录")
    expected = str(data.get("state") or "")
    if not expected or not state or not secrets.compare_digest(expected, str(state)):
        raise SsoRuntimeError("SSO_STATE_INVALID", "统一认证状态校验失败")
    return data


def begin_url(request, connection, *, next_url="/"):
    cfg = connection.config_json or {}
    if connection.adapter_code == "SSO_CAS":
        flow = _flow(request, connection, next_url=next_url)
        callback = _absolute(request, "hr-sso-callback", connection_id=connection.pk) + "?" + urlencode({"state": flow["state"]})
        login_url = _join(connection.base_url, cfg.get("login_path"))
        _runtime_https_required(login_url)
        return login_url + "?" + urlencode({str(cfg.get("service_parameter") or "service"): callback})
    if connection.adapter_code in {"SSO_OAUTH2", "SSO_OIDC"}:
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        nonce = secrets.token_urlsafe(24) if connection.adapter_code == "SSO_OIDC" else ""
        flow = _flow(request, connection, next_url=next_url, nonce=nonce, verifier=verifier)
        callback = _absolute(request, "hr-sso-callback", connection_id=connection.pk)
        if connection.adapter_code == "SSO_OIDC":
            doc = oidc_discovery(connection)
            authorize_url = doc["authorization_endpoint"]
            scope = str(cfg.get("scope") or "openid profile email")
        else:
            authorize_url = _join(connection.base_url, cfg.get("authorize_path"))
            scope = str(cfg.get("scope") or "profile")
        _runtime_https_required(authorize_url)
        params = {"response_type":"code","client_id":cfg["client_id"],"redirect_uri":callback,"scope":scope,"state":flow["state"],"code_challenge":challenge,"code_challenge_method":"S256"}
        if nonce: params["nonce"] = nonce
        return authorize_url + ("&" if "?" in authorize_url else "?") + urlencode(params)
    raise SsoRuntimeError("SSO_INTERACTIVE_LOGIN_UNSUPPORTED", "该统一认证方式使用专用登录表单")


def oidc_discovery(connection):
    cfg = connection.config_json or {}
    url = _join(connection.base_url, cfg.get("discovery_path") or "/.well-known/openid-configuration")
    response = _request("GET", url)
    if response.status_code != 200:
        raise SsoRuntimeError("OIDC_DISCOVERY_ERROR", f"OIDC Discovery 返回 HTTP {response.status_code}", status=502)
    try: doc = response.json()
    except ValueError as exc: raise SsoRuntimeError("OIDC_DISCOVERY_INVALID", "OIDC Discovery 不是合法 JSON", status=502) from exc
    for key in ("issuer","authorization_endpoint","token_endpoint","jwks_uri"):
        if not str(doc.get(key) or "").strip(): raise SsoRuntimeError("OIDC_DISCOVERY_INVALID", f"OIDC Discovery 缺少 {key}", status=502)
    for key in ("authorization_endpoint","token_endpoint","jwks_uri"):
        _runtime_https_required(doc[key])
    return doc


def _cas_claims(connection, ticket: str, service: str):
    cfg = connection.config_json or {}
    url = _join(connection.base_url, cfg.get("validate_path"))
    response = _request("GET", url, params={"ticket":ticket,"service":service})
    if response.status_code != 200: raise SsoRuntimeError("CAS_VALIDATE_ERROR", f"CAS 校验端点返回 HTTP {response.status_code}", status=502)
    try: root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError as exc: raise SsoRuntimeError("CAS_RESPONSE_INVALID", "CAS 校验返回格式无效", status=502) from exc
    failure = next((x for x in root.iter() if x.tag.endswith("authenticationFailure")), None)
    if failure is not None: raise SsoRuntimeError("CAS_TICKET_REJECTED", "CAS Ticket 校验失败", status=401)
    success = next((x for x in root.iter() if x.tag.endswith("authenticationSuccess")), None)
    if success is None: raise SsoRuntimeError("CAS_RESPONSE_INVALID", "CAS 响应缺少成功节点", status=502)
    user = next((x.text for x in success.iter() if x.tag.endswith("user") and x.text), "")
    claims = {"user": user}
    for node in success.iter():
        if node is success or list(node): continue
        key = node.tag.rsplit("}",1)[-1]
        if key != "user" and node.text: claims[key] = node.text.strip()
    claims["sub"] = user
    return claims


def _oauth_claims(connection, code: str, flow: dict, *, oidc=False):
    cfg, sec = connection.config_json or {}, _secrets(connection)
    token_url = oidc_discovery(connection)["token_endpoint"] if oidc else _join(connection.base_url, cfg.get("token_path"))
    redirect_uri = flow["redirect_uri"]
    token_data={"grant_type":"authorization_code","code":code,"redirect_uri":redirect_uri,"client_id":cfg["client_id"],"code_verifier":flow.get("verifier","")}
    token_headers={"Accept":"application/json"}
    token_auth_method=str(cfg.get("token_auth_method") or "client_secret_post").strip().lower()
    if token_auth_method == "client_secret_basic":
        raw=f"{cfg['client_id']}:{sec.get('client_secret','')}".encode("utf-8")
        token_headers["Authorization"]="Basic "+base64.b64encode(raw).decode("ascii")
    elif token_auth_method == "client_secret_post":
        token_data["client_secret"]=sec.get("client_secret","")
    else:
        raise SsoRuntimeError("SSO_TOKEN_AUTH_METHOD_UNSUPPORTED", "Token 端点客户端认证方式不受支持")
    response = _request("POST", token_url, data=token_data, headers=token_headers)
    if not 200 <= response.status_code < 300: raise SsoRuntimeError("SSO_TOKEN_EXCHANGE_FAILED", f"Token 交换失败 HTTP {response.status_code}", status=401)
    try: token = response.json()
    except ValueError as exc: raise SsoRuntimeError("SSO_TOKEN_RESPONSE_INVALID", "Token 响应不是合法 JSON", status=502) from exc
    access_token = str(token.get("access_token") or "")
    if not access_token: raise SsoRuntimeError("SSO_ACCESS_TOKEN_MISSING", "Token 响应缺少 access_token", status=401)
    if oidc:
        id_token = str(token.get("id_token") or "")
        if not id_token: raise SsoRuntimeError("OIDC_ID_TOKEN_MISSING", "OIDC 响应缺少 id_token", status=401)
        claims = verify_id_token(connection, id_token, expected_nonce=str(flow.get("nonce") or ""))
        return claims
    userinfo_url = _join(connection.base_url, cfg.get("userinfo_path"))
    userinfo = _request("GET", userinfo_url, headers={"Authorization":"Bearer "+access_token,"Accept":"application/json"})
    if userinfo.status_code != 200: raise SsoRuntimeError("OAUTH_USERINFO_FAILED", f"用户信息接口返回 HTTP {userinfo.status_code}", status=401)
    try: return userinfo.json()
    except ValueError as exc: raise SsoRuntimeError("OAUTH_USERINFO_INVALID", "用户信息接口未返回合法 JSON", status=502) from exc


def verify_id_token(connection, token: str, *, expected_nonce: str):
    cfg = connection.config_json or {}; doc = oidc_discovery(connection)
    try: header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc: raise SsoRuntimeError("OIDC_ID_TOKEN_INVALID", "ID Token 头无效", status=401) from exc
    alg = str(header.get("alg") or "")
    if alg not in {"RS256","RS384","RS512","ES256","ES384"}: raise SsoRuntimeError("OIDC_ALG_NOT_ALLOWED", "ID Token 签名算法不在允许列表", status=401)
    jwks_response = _request("GET", doc["jwks_uri"])
    if jwks_response.status_code != 200:
        raise SsoRuntimeError("OIDC_JWKS_ERROR", f"OIDC JWKS 返回 HTTP {jwks_response.status_code}", status=502)
    try: keys = jwks_response.json().get("keys", [])
    except Exception as exc: raise SsoRuntimeError("OIDC_JWKS_INVALID", "OIDC JWKS 无效", status=502) from exc
    kid = str(header.get("kid") or "")
    jwk = next((x for x in keys if str(x.get("kid") or "") == kid), None)
    if jwk is None: raise SsoRuntimeError("OIDC_SIGNING_KEY_NOT_FOUND", "未找到 ID Token 对应签名密钥", status=401)
    try:
        key = jwt.PyJWK.from_dict(jwk).key
        claims = jwt.decode(token, key=key, algorithms=[alg], audience=cfg["client_id"], issuer=doc["issuer"], options={"require":["exp","iss","aud","sub"]})
    except jwt.PyJWTError as exc: raise SsoRuntimeError("OIDC_ID_TOKEN_INVALID", "ID Token 验签或声明校验失败", status=401) from exc
    if not expected_nonce or not secrets.compare_digest(str(claims.get("nonce") or ""), expected_nonce):
        raise SsoRuntimeError("OIDC_NONCE_INVALID", "OIDC Nonce 校验失败", status=401)
    return claims


def _claim(claims, key, *, fallback=""):
    key = str(key or "").strip()
    if key == "user": return str(claims.get("user") or claims.get("sub") or "").strip()
    value = claims.get(key) if key else None
    if isinstance(value, (list, tuple)): value = value[0] if value else ""
    return str(value if value is not None else fallback).strip()


@dataclass(frozen=True)
class ResolvedIdentity:
    user: object
    staff: object
    subject: str
    staff_no: str


def resolve_identity(connection, claims) -> ResolvedIdentity:
    from hr_staff.models import HrAccountLink, HrEmploymentRelationship, HrExternalIdentityMapping, HrStaffMaster
    from base.auth_backends import get_allowed_company_ids

    cfg = connection.config_json or {}
    subject_key = str(cfg.get("subject_claim") or ("user" if connection.adapter_code in {"SSO_CAS","SSO_LDAP"} else "sub"))
    staff_key = str(cfg.get("staff_no_claim") or cfg.get("staff_no_attribute") or "")
    subject, staff_no = _claim(claims, subject_key), _claim(claims, staff_key)
    if not subject: raise SsoRuntimeError("SSO_SUBJECT_MISSING", "学校认证结果缺少唯一身份标识", status=401)
    if not staff_no: raise SsoRuntimeError("SSO_STAFF_NO_MISSING", "学校认证结果缺少工号映射字段", status=401)

    try: staff = HrStaffMaster.objects.get(tenant_id=connection.tenant_id, staff_no=staff_no)
    except HrStaffMaster.DoesNotExist as exc: raise SsoRuntimeError("SSO_STAFF_NOT_FOUND", "该工号尚未进入本校 HR03 教职工主档", status=403) from exc
    except HrStaffMaster.MultipleObjectsReturned as exc: raise SsoRuntimeError("SSO_STAFF_AMBIGUOUS", "该工号在本校主档不唯一", status=403) from exc

    today = timezone.localdate()
    active = HrEmploymentRelationship.objects.filter(tenant_id=connection.tenant_id, staff_id=staff, status="ACTIVE", effective_from__lte=today).filter(Q(effective_to__isnull=True)|Q(effective_to__gt=today)).exists()
    if not active: raise SsoRuntimeError("SSO_EMPLOYMENT_INACTIVE", "该教职工当前不存在有效聘用关系", status=403)

    links = list(HrAccountLink.objects.filter(tenant_id=connection.tenant_id, staff_id=staff, link_status=HrAccountLink.LinkStatus.ACTIVE, auth_user_id__isnull=False)[:2])
    if len(links) != 1: raise SsoRuntimeError("SSO_ACCOUNT_LINK_REQUIRED" if not links else "SSO_ACCOUNT_LINK_AMBIGUOUS", "本地账号与 HR03 教职工映射未准备好或不唯一", status=403)
    user = get_user_model().objects.filter(pk=links[0].auth_user_id).first()
    if not user or not user.is_active: raise SsoRuntimeError("SSO_LOCAL_ACCOUNT_INACTIVE", "本地账号不存在或已停用", status=403)
    employee = getattr(user, "employee_get", None)
    if not employee or not getattr(employee, "is_active", False): raise SsoRuntimeError("SSO_EMPLOYEE_BRIDGE_INACTIVE", "兼容账号桥接不存在或已停用", status=403)
    if not getattr(user, "is_superuser", False) and int(connection.tenant_id) not in {int(x) for x in get_allowed_company_ids(user)}:
        raise SsoRuntimeError("SSO_TENANT_ACCESS_DENIED", "该账号没有当前学校访问范围", status=403)

    existing = HrExternalIdentityMapping.objects.filter(tenant_id=connection.tenant_id, system_code=connection.code, external_subject=subject).first()
    if existing:
        if existing.mapping_status != "ACTIVE" or existing.staff_id_id != staff.id:
            raise SsoRuntimeError("SSO_IDENTITY_BINDING_CONFLICT", "外部身份与教职工绑定冲突", status=403)
    else:
        changed = HrExternalIdentityMapping.objects.filter(tenant_id=connection.tenant_id, system_code=connection.code, staff_id=staff, mapping_status="ACTIVE").exclude(external_subject=subject).exists()
        if changed: raise SsoRuntimeError("SSO_SUBJECT_CHANGED", "学校返回的外部身份标识已变化，必须由管理员人工复核", status=403)
        if not _bool(cfg.get("allow_first_login_binding"), False):
            raise SsoRuntimeError("SSO_IDENTITY_PREBIND_REQUIRED", "该外部身份尚未预绑定；请管理员确认后再登录", status=403)
        try:
            with transaction.atomic():
                HrExternalIdentityMapping.objects.create(tenant_id=connection.tenant_id, staff_id=staff, system_code=connection.code, external_subject=subject, mapping_status="ACTIVE", valid_from=today)
        except IntegrityError as exc:
            raise SsoRuntimeError("SSO_IDENTITY_BINDING_CONFLICT", "外部身份绑定发生并发冲突，请管理员复核", status=403) from exc
    return ResolvedIdentity(user=user, staff=staff, subject=subject, staff_no=staff_no)


def runtime_contract_hash(connection) -> str:
    """Fingerprint the runtime-relevant SSO contract without exposing secrets.

    credential_updated_at participates so rotating a secret invalidates prior
    acceptance evidence even though the secret value is never hashed or stored.
    """
    payload = {
        "schema": "hr.sso.runtime.v1",
        "tenantId": int(connection.tenant_id),
        "code": str(connection.code),
        "adapterCode": str(connection.adapter_code),
        "baseUrl": str(connection.base_url or ""),
        "config": connection.config_json or {},
        "credentialUpdatedAt": connection.credential_updated_at.isoformat() if connection.credential_updated_at else "",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record_evidence(connection, *, protocol, status, code="", subject="", staff_no="", user_id=None, detail=None):
    safe_detail = {str(k): str(v)[:120] for k,v in (detail or {}).items() if k in {"phase","provider_status","reason"}}
    fingerprint = hashlib.sha256(subject.encode("utf-8")).hexdigest() if subject else ""
    try:
        return SsoLoginEvidence.objects.create(tenant_id=connection.tenant_id, connection=connection, protocol=protocol[:16], status=status, failure_code=code[:64], runtime_contract_hash=runtime_contract_hash(connection), subject_fingerprint=fingerprint, staff_no=staff_no[:64], auth_user_id=user_id, detail_json=safe_detail)
    except Exception:
        return None


def complete_callback(request, connection):
    state = request.GET.get("state", "")
    flow = _consume_flow(request, connection, state)
    flow["redirect_uri"] = _absolute(request, "hr-sso-callback", connection_id=connection.pk)
    if request.GET.get("error"):
        raise SsoRuntimeError("SSO_PROVIDER_REJECTED", "学校统一认证拒绝了本次登录", status=401)
    if connection.adapter_code == "SSO_CAS":
        ticket = str(request.GET.get("ticket") or "")
        if not ticket: raise SsoRuntimeError("CAS_TICKET_MISSING", "CAS 回调缺少 Ticket", status=401)
        service = flow["redirect_uri"] + "?" + urlencode({"state":flow["state"]})
        claims = _cas_claims(connection, ticket, service)
    else:
        code = str(request.GET.get("code") or "")
        if not code: raise SsoRuntimeError("SSO_CODE_MISSING", "统一认证回调缺少授权码", status=401)
        claims = _oauth_claims(connection, code, flow, oidc=connection.adapter_code == "SSO_OIDC")
    identity = resolve_identity(connection, claims)
    return identity, flow["next"]


def ldap_authenticate(connection, *, username: str, password: str):
    cfg = connection.config_json or {}; username=str(username or "").strip(); password=str(password or "")
    if not username or not password: raise SsoRuntimeError("LDAP_CREDENTIAL_REQUIRED", "请输入学校账号和密码", status=401)
    mode=str(cfg.get("security_mode") or "LDAPS").upper()
    if mode == "PLAIN" and not (getattr(settings,"DEBUG",False) and getattr(settings,"HR_SSO_ALLOW_INSECURE_FOR_TESTS",False)):
        raise SsoRuntimeError("LDAP_TLS_REQUIRED", "生产环境禁止明文 LDAP")
    host=str(cfg.get("host") or "").strip(); _require_allowed_host(host)
    try:
        import ldap3
        from ldap3.utils.conv import escape_filter_chars
    except Exception as exc:
        raise SsoRuntimeError("LDAP_CLIENT_MISSING", "服务器未安装受支持的 LDAP 客户端 ldap3；不会回退到不安全实现", status=503) from exc
    port=int(cfg.get("port") or (636 if mode=="LDAPS" else 389)); use_ssl=mode=="LDAPS"
    server=ldap3.Server(host, port=port, use_ssl=use_ssl, connect_timeout=float(getattr(settings,"HR_INTEGRATION_HTTP_TIMEOUT_SECONDS",5)))
    bind_dn=str(cfg.get("bind_dn") or "").strip(); bind_password=_secrets(connection).get("bind_password","")
    try:
        auto_bind = ldap3.AUTO_BIND_TLS_BEFORE_BIND if mode == "STARTTLS" else ldap3.AUTO_BIND_NO_TLS
        service=ldap3.Connection(server,user=bind_dn or None,password=bind_password or None,auto_bind=auto_bind,receive_timeout=float(getattr(settings,"HR_INTEGRATION_HTTP_TIMEOUT_SECONDS",5)))
        flt=str(cfg.get("user_filter") or "(uid={username})").replace("{username}",escape_filter_chars(username))
        attrs=list({str(cfg.get("staff_no_attribute") or "uid"), str(cfg.get("username_attribute") or "uid")})
        if not service.search(str(cfg.get("base_dn") or ""),flt,attributes=attrs,size_limit=2) or len(service.entries)!=1:
            raise SsoRuntimeError("LDAP_USER_NOT_FOUND","LDAP 账号不存在或匹配不唯一",status=401)
        entry=service.entries[0]; user_dn=str(entry.entry_dn)
        user_auto_bind = ldap3.AUTO_BIND_TLS_BEFORE_BIND if mode == "STARTTLS" else ldap3.AUTO_BIND_NO_TLS
        user_conn=ldap3.Connection(server,user=user_dn,password=password,auto_bind=user_auto_bind,receive_timeout=float(getattr(settings,"HR_INTEGRATION_HTTP_TIMEOUT_SECONDS",5)))
        staff_attr=str(cfg.get("staff_no_attribute") or "uid")
        staff_no=str(getattr(entry,staff_attr).value if hasattr(entry,staff_attr) else "").strip()
        return {"user":username,"sub":username,staff_attr:staff_no}
    except SsoRuntimeError: raise
    except Exception as exc: raise SsoRuntimeError("LDAP_BIND_FAILED","LDAP 认证失败",status=401) from exc


def prebind_identity(connection, *, staff_no: str, external_subject: str, actor_user_id=None):
    from hr_staff.models import HrAccountLink, HrEmploymentRelationship, HrExternalIdentityMapping, HrStaffMaster
    staff_no=str(staff_no or "").strip(); subject=str(external_subject or "").strip()
    if not staff_no or not subject: raise SsoRuntimeError("SSO_PREBIND_INPUT_REQUIRED", "工号和外部 Subject 都不能为空")
    staff=HrStaffMaster.objects.filter(tenant_id=connection.tenant_id,staff_no=staff_no).first()
    if not staff: raise SsoRuntimeError("SSO_STAFF_NOT_FOUND", "工号不存在于本校 HR03 主档", status=404)
    today=timezone.localdate()
    active=HrEmploymentRelationship.objects.filter(tenant_id=connection.tenant_id,staff_id=staff,status="ACTIVE",effective_from__lte=today).filter(Q(effective_to__isnull=True)|Q(effective_to__gt=today)).exists()
    if not active: raise SsoRuntimeError("SSO_EMPLOYMENT_INACTIVE", "该教职工当前不存在有效聘用关系", status=409)
    links=list(HrAccountLink.objects.filter(tenant_id=connection.tenant_id,staff_id=staff,link_status=HrAccountLink.LinkStatus.ACTIVE,auth_user_id__isnull=False)[:2])
    if len(links)!=1: raise SsoRuntimeError("SSO_ACCOUNT_LINK_REQUIRED" if not links else "SSO_ACCOUNT_LINK_AMBIGUOUS", "请先完成唯一的本地账号映射", status=409)
    same_staff=HrExternalIdentityMapping.objects.filter(tenant_id=connection.tenant_id,system_code=connection.code,staff_id=staff,mapping_status="ACTIVE")
    if same_staff.exclude(external_subject=subject).exists(): raise SsoRuntimeError("SSO_SUBJECT_CHANGED", "该工号已经绑定其他 Subject，请先人工复核", status=409)
    other=HrExternalIdentityMapping.objects.filter(tenant_id=connection.tenant_id,system_code=connection.code,external_subject=subject).exclude(staff_id=staff).first()
    if other: raise SsoRuntimeError("SSO_IDENTITY_BINDING_CONFLICT", "该 Subject 已绑定其他教职工", status=409)
    obj,created=HrExternalIdentityMapping.objects.get_or_create(tenant_id=connection.tenant_id,system_code=connection.code,external_subject=subject,defaults={"staff_id":staff,"mapping_status":"ACTIVE","valid_from":today})
    if obj.staff_id_id!=staff.id or obj.mapping_status!="ACTIVE": raise SsoRuntimeError("SSO_IDENTITY_BINDING_CONFLICT", "现有身份绑定状态冲突", status=409)
    from .services import record_audit
    fingerprint=hashlib.sha256(subject.encode("utf-8")).hexdigest()
    record_audit(tenant_id=connection.tenant_id,actor_user_id=actor_user_id,event_type="SSO_IDENTITY_PREBOUND",connection_code=connection.code,summary=f"预绑定统一认证身份 → 工号 {staff_no}",payload={"staffNo":staff_no,"subjectFingerprint":fingerprint})
    return {"created":created,"staffNo":staff_no,"subjectFingerprint":fingerprint,"authUserId":links[0].auth_user_id}


def identity_binding_rows(connection):
    from hr_staff.models import HrExternalIdentityMapping
    rows=[]
    for obj in HrExternalIdentityMapping.objects.filter(tenant_id=connection.tenant_id,system_code=connection.code,mapping_status="ACTIVE").select_related("staff_id").order_by("staff_id__staff_no")[:200]:
        rows.append({"staff_no":obj.staff_id.staff_no,"fingerprint":hashlib.sha256(obj.external_subject.encode("utf-8")).hexdigest(),"status":obj.mapping_status})
    return rows
