from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from hr_integration.adapters import AdapterError, _require_allowed_host, get_spec, validate_configuration
from hr_integration.crypto import decrypt_secret_payload
from hr_integration.models import IntegrationConnection, SsoLoginEvidence
from hr_integration.sso_runtime import runtime_contract_hash
from hr_integration.ui_catalog import ADAPTER_UI


class Command(BaseCommand):
    help = "Preflight one school's SSO connection without printing secrets or impersonating a user."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True)
        parser.add_argument("--connection", required=True, help="Integration connection code")
        parser.add_argument("--public-base-url", required=True, help="Public HR URL, e.g. https://hr.example.edu.cn/")
        parser.add_argument("--require-live-ready", action="store_true", help="Require enabled connection, prebound identity and successful SSO evidence")
        parser.add_argument("--json-output", default="")

    def handle(self, *args, **options):
        tenant_id = int(options["tenant"])
        if tenant_id <= 0:
            raise CommandError("TENANT_INVALID")
        code = str(options["connection"]).strip().upper()
        connection = IntegrationConnection.objects.filter(
            tenant_id=tenant_id, code=code, category=IntegrationConnection.Category.SSO
        ).first()
        if not connection:
            raise CommandError("SSO_CONNECTION_NOT_FOUND")

        checks = []
        def add(check_id, ok, detail, *, blocking=True):
            checks.append({"id": check_id, "ok": bool(ok), "blocking": bool(blocking), "detail": str(detail)[:240]})

        if connection.adapter_code not in {"SSO_CAS", "SSO_OAUTH2", "SSO_OIDC", "SSO_LDAP"}:
            raise CommandError("SSO_ADAPTER_UNSUPPORTED")
        spec = get_spec(connection.adapter_code)

        try:
            secrets = decrypt_secret_payload(connection.secret_ciphertext) if connection.secret_ciphertext else {}
        except Exception:
            secrets = {}
            add("CREDENTIAL_DECRYPT", False, "接口密钥无法解密，请重新录入")
        else:
            add("CREDENTIAL_DECRYPT", True, "密钥可读取但不会输出")

        try:
            validate_configuration(
                category=connection.category, adapter_code=connection.adapter_code,
                base_url=connection.base_url, config=connection.config_json or {}, secrets=secrets,
            )
            add("CONFIG_CONTRACT", True, "协议配置字段完整")
        except AdapterError as exc:
            add("CONFIG_CONTRACT", False, f"{exc.code}: {exc}")

        missing_secret = [key for key in spec.required_secret if not str(secrets.get(key, "")).strip()]
        add("REQUIRED_SECRET", not missing_secret, "密钥项齐备" if not missing_secret else "缺少: " + ", ".join(missing_secret))

        cfg = connection.config_json or {}
        provider_host = str(cfg.get("host") or "").strip() if connection.adapter_code == "SSO_LDAP" else (urlparse(connection.base_url).hostname or "")
        try:
            _require_allowed_host(provider_host)
            add("PROVIDER_ALLOWLIST", True, f"{provider_host} 已进入 HR_INTEGRATION_ALLOWED_HOSTS")
        except AdapterError as exc:
            add("PROVIDER_ALLOWLIST", False, f"{exc.code}: {exc}")

        public_base = str(options["public_base_url"]).strip().rstrip("/") + "/"
        public = urlparse(public_base)
        allow_test_http = bool(getattr(settings, "DEBUG", False)) and bool(getattr(settings, "HR_SSO_ALLOW_INSECURE_FOR_TESTS", False))
        public_https_ok = bool(public.hostname and (public.scheme == "https" or (public.scheme == "http" and allow_test_http)))
        add("PUBLIC_HTTPS", public_https_ok, "公开人事地址可用于 SSO 回调" if public_https_ok else "生产公开地址必须使用 HTTPS")

        provider_tls_ok = True
        if connection.adapter_code != "SSO_LDAP":
            parsed = urlparse(connection.base_url)
            provider_tls_ok = parsed.scheme == "https" or (parsed.scheme == "http" and allow_test_http)
        else:
            provider_tls_ok = str(cfg.get("security_mode") or "LDAPS").upper() in {"LDAPS", "STARTTLS"} or allow_test_http
        add("PROVIDER_TLS", provider_tls_ok, "认证提供方使用受保护传输" if provider_tls_ok else "生产环境禁止 HTTP/明文 LDAP")

        def absolute(name):
            return urljoin(public_base, reverse(name, kwargs={"connection_id": connection.pk}).lstrip("/"))
        endpoints = {
            "startUrl": absolute("hr-sso-start"),
            "logoutUrl": urljoin(public_base, reverse("hr-sso-logout").lstrip("/")),
        }
        if connection.adapter_code == "SSO_LDAP":
            endpoints["loginUrl"] = absolute("hr-sso-ldap")
        else:
            endpoints["callbackUrl"] = absolute("hr-sso-callback")

        try:
            from hr_staff.models import HrAccountLink, HrEmploymentRelationship, HrExternalIdentityMapping, HrStaffMaster
            today = timezone.localdate()
            active_staff_ids = HrEmploymentRelationship.objects.filter(
                tenant_id=tenant_id, status="ACTIVE", effective_from__lte=today
            ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=today)).values_list("staff_id", flat=True)
            active_staff_count = HrStaffMaster.objects.filter(tenant_id=tenant_id, pk__in=active_staff_ids).count()
            account_link_count = HrAccountLink.objects.filter(
                tenant_id=tenant_id, staff_id__in=active_staff_ids,
                link_status=HrAccountLink.LinkStatus.ACTIVE, auth_user_id__isnull=False,
            ).count()
            prebound_count = HrExternalIdentityMapping.objects.filter(
                tenant_id=tenant_id, system_code=connection.code, mapping_status="ACTIVE"
            ).count()
            add("HR03_ACTIVE_STAFF", active_staff_count > 0, f"有效教职工 {active_staff_count} 人", blocking=False)
            add("LOCAL_ACCOUNT_LINK", account_link_count > 0, f"已建立本地账号映射 {account_link_count} 人", blocking=options["require_live_ready"])
            add("IDENTITY_PREBIND", prebound_count > 0, f"已预绑定外部身份 {prebound_count} 人", blocking=options["require_live_ready"])
        except Exception as exc:
            active_staff_count = account_link_count = prebound_count = 0
            add("HR03_IDENTITY_CHECK", False, f"HR03 身份底座检查失败: {type(exc).__name__}", blocking=options["require_live_ready"])

        current_runtime_hash = runtime_contract_hash(connection)
        success_qs = SsoLoginEvidence.objects.filter(
            tenant_id=tenant_id, connection=connection, status=SsoLoginEvidence.Status.SUCCESS,
            runtime_contract_hash=current_runtime_hash,
        )
        failure_qs = SsoLoginEvidence.objects.filter(
            tenant_id=tenant_id, connection=connection, status=SsoLoginEvidence.Status.FAILED
        )
        success_count, failure_count = success_qs.count(), failure_qs.count()
        last_failure = failure_qs.order_by("-happened_at").values("failure_code", "happened_at").first()
        add("RUNTIME_LOGIN_EVIDENCE", success_count > 0, f"成功登录证据 {success_count} 条", blocking=options["require_live_ready"])
        add("CONNECTION_ENABLED", connection.enabled, "连接已启用" if connection.enabled else "连接尚未启用", blocking=options["require_live_ready"])

        blocking_failures = [item for item in checks if item["blocking"] and not item["ok"]]
        status = "PASS" if not blocking_failures else "BLOCKED"
        ui = ADAPTER_UI.get(connection.adapter_code, {})
        result = {
            "status": status,
            "tenantId": tenant_id,
            "connection": {
                "code": connection.code, "name": connection.name, "adapterCode": connection.adapter_code,
                "protocol": ui.get("protocol", connection.adapter_code), "enabled": connection.enabled,
            },
            "registration": endpoints,
            "schoolMaterials": list(ui.get("materials", [])),
            "checks": checks,
            "identity": {
                "activeStaffCount": active_staff_count,
                "accountLinkCount": account_link_count,
                "preboundIdentityCount": prebound_count,
            },
            "runtimeEvidence": {
                "successCount": success_count, "currentRuntimeContractHash": current_runtime_hash, "failureCount": failure_count,
                "lastFailureCode": (last_failure or {}).get("failure_code", ""),
                "lastFailureAt": str((last_failure or {}).get("happened_at", "")),
            },
        }
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if options["json_output"]:
            path = Path(options["json_output"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered + "\n", encoding="utf-8")
        self.stdout.write(rendered)
        if blocking_failures:
            raise CommandError("SSO_SCHOOL_PREFLIGHT_BLOCKED: " + ",".join(x["id"] for x in blocking_failures))
        self.stdout.write(self.style.SUCCESS("SSO school preflight: PASS"))
