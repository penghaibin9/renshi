from __future__ import annotations

import smtplib
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from django.conf import settings


class AdapterError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AdapterSpec:
    code: str
    category: str
    name: str
    protocol: str
    required_config: tuple[str, ...] = ()
    required_secret: tuple[str, ...] = ()
    network_probe: str = "HTTP"


_SPECS = (
    AdapterSpec("SSO_CAS", "SSO", "CAS", "CAS", ("login_path", "validate_path", "staff_no_claim"), (), "HTTP"),
    AdapterSpec("SSO_OAUTH2", "SSO", "OAuth2", "OAUTH2", ("authorize_path", "token_path", "userinfo_path", "client_id", "subject_claim", "staff_no_claim"), ("client_secret",), "HTTP"),
    AdapterSpec("SSO_OIDC", "SSO", "OIDC", "OIDC", ("client_id", "staff_no_claim"), ("client_secret",), "HTTP"),
    AdapterSpec("SSO_LDAP", "SSO", "LDAP / LDAPS", "LDAP", ("host", "base_dn", "user_filter", "staff_no_attribute"), ("bind_password",), "LDAP"),
    AdapterSpec("MASTERDATA_HTTP_JSON", "MASTER_DATA", "数据中台 / 主数据 HTTP JSON", "HTTP_JSON", ("health_path",), ("token",), "HTTP"),
    AdapterSpec("RESEARCH_HTTP_JSON", "RESEARCH", "科研项目/论文/成果 HTTP JSON", "HTTP_JSON", ("health_path",), ("token",), "HTTP"),
    AdapterSpec("ACADEMIC_HTTP_JSON", "ACADEMIC", "教务课程/工作量 HTTP JSON", "HTTP_JSON", ("health_path",), ("token",), "HTTP"),
    AdapterSpec("FINANCE_HTTP_JSON", "FINANCE", "财务支付/凭证/成本中心 HTTP JSON", "HTTP_JSON", ("health_path",), ("token",), "HTTP"),
    AdapterSpec("ATTENDANCE_HTTP_JSON", "ATTENDANCE", "门禁/一卡通/考勤机 HTTP JSON", "HTTP_JSON", ("health_path",), ("token",), "HTTP"),
    AdapterSpec("ESIGN_HTTP_JSON", "ESIGN", "电子签章 HTTP JSON", "HTTP_JSON", ("health_path",), ("app_secret",), "HTTP"),
    AdapterSpec("SMS_HTTP", "NOTIFICATION", "短信 HTTP", "HTTP_JSON", ("health_path",), ("token",), "HTTP"),
    AdapterSpec("EMAIL_SMTP", "NOTIFICATION", "邮件 SMTP", "SMTP", ("host", "port", "username"), ("password",), "SMTP"),
    AdapterSpec("WECOM", "NOTIFICATION", "企业微信", "HTTP_JSON", ("corp_id", "agent_id", "health_path"), ("corp_secret",), "HTTP"),
)
ADAPTERS = {x.code: x for x in _SPECS}


def catalog():
    return _SPECS


def get_spec(code: str) -> AdapterSpec:
    try: return ADAPTERS[str(code or "").strip().upper()]
    except KeyError as exc: raise AdapterError("UNKNOWN_ADAPTER", "未知 Adapter") from exc


def validate_configuration(*, category: str, adapter_code: str, base_url: str, config: dict, secrets: dict | None = None) -> AdapterSpec:
    spec = get_spec(adapter_code)
    if spec.category != category:
        raise AdapterError("CATEGORY_MISMATCH", f"{spec.name} 不属于 {category}")
    config = config or {}; secrets = secrets or {}
    missing = [x for x in spec.required_config if not str(config.get(x, "")).strip()]
    if missing: raise AdapterError("CONFIG_REQUIRED", "缺少配置: " + ", ".join(missing))
    if spec.protocol not in {"LDAP", "SMTP"}:
        parsed=urlparse(str(base_url or ""))
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise AdapterError("BASE_URL_INVALID", "Base URL 必须是完整 HTTP/HTTPS 地址")
    return spec


def _allowed_host(host: str) -> bool:
    configured=getattr(settings,"HR_INTEGRATION_ALLOWED_HOSTS",())
    if isinstance(configured,str): configured=[x.strip().lower() for x in configured.split(",") if x.strip()]
    allowed={str(x).strip().lower() for x in configured if str(x).strip()}
    if not allowed: return False
    host=str(host or "").lower().rstrip(".")
    return host in allowed or any(item.startswith("*.") and host.endswith(item[1:]) for item in allowed)


def _require_allowed_host(host: str):
    if not _allowed_host(host):
        raise AdapterError("HOST_NOT_ALLOWED", "目标主机未加入 HR_INTEGRATION_ALLOWED_HOSTS，禁止从后台发起探测")


def _http_probe(url: str, *, timeout: float):
    try:
        return requests.get(
            url,
            timeout=timeout,
            allow_redirects=False,
            headers={"User-Agent": "Yueke-HR-Integration-Probe/1.1"},
        )
    except requests.RequestException as exc:
        raise AdapterError("NETWORK_ERROR", "网络连接失败；详细异常已隐藏") from exc


def probe(*, category: str, adapter_code: str, base_url: str, config: dict, secrets: dict) -> dict:
    spec=validate_configuration(category=category,adapter_code=adapter_code,base_url=base_url,config=config,secrets=secrets)
    missing_secrets=[x for x in spec.required_secret if not str(secrets.get(x,"")).strip()]
    if missing_secrets: raise AdapterError("CREDENTIAL_REQUIRED", "缺少密钥项: " + ", ".join(missing_secrets))
    timeout=float(getattr(settings,"HR_INTEGRATION_HTTP_TIMEOUT_SECONDS",5) or 5)

    # SSO probes are protocol-aware but deliberately stop before impersonating a
    # real user login. They prove endpoint/configuration reachability only.
    if adapter_code in {"SSO_CAS", "SSO_OAUTH2", "SSO_OIDC"}:
        parsed=urlparse(base_url); _require_allowed_host(parsed.hostname or "")
        if adapter_code == "SSO_CAS":
            path=str(config.get("login_path") or "").strip()
            response=_http_probe(base_url.rstrip("/") + "/" + path.lstrip("/"), timeout=timeout)
            if not 200 <= response.status_code < 400:
                raise AdapterError("SSO_ENDPOINT_ERROR", f"CAS 登录端点返回 HTTP {response.status_code}")
            return {"status":"CONFIG_VALIDATED","summary":"CAS 登录端点可达；待真实 Ticket 登录验收","httpStatus":response.status_code}
        if adapter_code == "SSO_OAUTH2":
            path=str(config.get("authorize_path") or "").strip()
            response=_http_probe(base_url.rstrip("/") + "/" + path.lstrip("/"), timeout=timeout)
            if response.status_code == 404 or response.status_code >= 500:
                raise AdapterError("SSO_ENDPOINT_ERROR", f"OAuth2 授权端点返回 HTTP {response.status_code}")
            return {"status":"CONFIG_VALIDATED","summary":"OAuth2 授权端点可达；待授权码登录回放","httpStatus":response.status_code}
        discovery=str(config.get("discovery_path") or "/.well-known/openid-configuration").strip()
        response=_http_probe(base_url.rstrip("/") + "/" + discovery.lstrip("/"), timeout=timeout)
        if not 200 <= response.status_code < 300:
            raise AdapterError("OIDC_DISCOVERY_ERROR", f"OIDC Discovery 返回 HTTP {response.status_code}")
        try:
            document=response.json()
        except ValueError as exc:
            raise AdapterError("OIDC_DISCOVERY_INVALID", "OIDC Discovery 未返回合法 JSON") from exc
        required=("issuer","authorization_endpoint","token_endpoint","jwks_uri")
        missing=[key for key in required if not str(document.get(key,"")).strip()]
        if missing:
            raise AdapterError("OIDC_DISCOVERY_INVALID", "OIDC Discovery 缺少: " + ", ".join(missing))
        return {"status":"CONFIG_VALIDATED","summary":"OIDC Discovery 校验通过；待真实授权码登录验收","httpStatus":response.status_code}

    if spec.network_probe=="HTTP":
        parsed=urlparse(base_url); _require_allowed_host(parsed.hostname or "")
        path=str(config.get("health_path") or "").strip()
        url=base_url.rstrip("/") + ("/"+path.lstrip("/") if path else "")
        response=_http_probe(url, timeout=timeout)
        if not 200 <= response.status_code < 400:
            raise AdapterError("HTTP_STATUS_ERROR", f"目标返回 HTTP {response.status_code}")
        return {"status":"VERIFIED","summary":f"{spec.name} 连通性验证通过","httpStatus":response.status_code}
    if spec.network_probe=="SMTP":
        host=str(config["host"]); _require_allowed_host(host)
        try:
            with smtplib.SMTP(host,int(config.get("port") or 25),timeout=timeout) as client:
                code,_=client.noop()
        except Exception as exc:
            raise AdapterError("NETWORK_ERROR","SMTP 连接失败；详细异常已隐藏") from exc
        if int(code)>=400: raise AdapterError("SMTP_STATUS_ERROR",f"SMTP 返回 {code}")
        return {"status":"VERIFIED","summary":"SMTP 连通性验证通过","smtpCode":int(code)}
    # LDAP deliberately validates the contract only; adding arbitrary LDAP network
    # calls to the web worker would require a reviewed LDAP client/timeout/TLS policy.
    host=str(config.get("host") or ""); _require_allowed_host(host)
    return {"status":"CONFIG_VALIDATED","summary":"LDAP 配置合同已校验；真实绑定测试由部署验收命令执行"}

