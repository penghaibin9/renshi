from __future__ import annotations

import hashlib
import json
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .adapters import AdapterError, probe, validate_configuration
from .crypto import decrypt_secret_payload, encrypt_secret_payload
from .models import IntegrationAuditEvent, IntegrationConnection, IntegrationTestRun


class IntegrationError(ValueError):
    def __init__(self, code: str, message: str): self.code=code; super().__init__(message)


def record_audit(*, tenant_id, actor_user_id, event_type, connection_code, summary, payload=None):
    IntegrationAuditEvent.objects.create(tenant_id=tenant_id,actor_user_id=actor_user_id,event_type=event_type,connection_code=connection_code,summary=summary[:255],payload_json=payload or {})


def _audit(**kwargs):
    return record_audit(**kwargs)


def save_connection(*, tenant_id:int, actor_user_id:int|None, instance:IntegrationConnection|None, code:str,name:str,category:str,adapter_code:str,base_url:str,enabled:bool,config:dict,secrets:dict|None=None):
    obj=instance or IntegrationConnection(tenant_id=tenant_id,created_by=actor_user_id)
    if obj.pk and obj.tenant_id!=tenant_id:
        raise IntegrationError("TENANT_MISMATCH","连接不属于当前学校")
    adapter_changed = bool(obj.pk and obj.adapter_code and obj.adapter_code != adapter_code)
    try:
        # Credentials belong to one Adapter contract. Never silently reuse an old
        # protocol secret after CAS/OAuth/OIDC/LDAP (or any other Adapter) changes.
        if adapter_changed and not secrets:
            effective_secrets = {}
        else:
            effective_secrets = secrets or (decrypt_secret_payload(obj.secret_ciphertext) if obj.secret_ciphertext else {})
        spec=validate_configuration(category=category,adapter_code=adapter_code,base_url=base_url,config=config,secrets=effective_secrets)
    except AdapterError as exc:
        raise IntegrationError(exc.code,str(exc)) from exc
    except Exception as exc:
        raise IntegrationError("CREDENTIAL_DECRYPT_FAILED", "已有接口密钥无法解密，请重新录入") from exc
    if enabled:
        missing=[key for key in spec.required_secret if not str(effective_secrets.get(key,"")).strip()]
        if missing:
            raise IntegrationError("CREDENTIAL_REQUIRED", "启用该连接前必须保存密钥项: " + ", ".join(missing))
    with transaction.atomic():
        obj.code=code;obj.name=name;obj.category=category;obj.adapter_code=adapter_code;obj.base_url=base_url;obj.enabled=bool(enabled);obj.config_json=config;obj.updated_by=actor_user_id
        if adapter_changed and not secrets:
            obj.secret_ciphertext="";obj.credential_updated_at=None
        elif secrets:
            obj.secret_ciphertext=encrypt_secret_payload(secrets);obj.credential_updated_at=timezone.now()
        obj.status=IntegrationConnection.Status.CONFIGURED
        try:
            obj.full_clean();obj.save()
        except ValidationError as exc:
            raise IntegrationError("CONNECTION_INVALID", "; ".join(exc.messages)) from exc
        _audit(tenant_id=tenant_id,actor_user_id=actor_user_id,event_type="CONNECTION_SAVED",connection_code=obj.code,summary=f"保存接口 {obj.code}",payload={"category":obj.category,"adapter":obj.adapter_code,"enabled":obj.enabled,"hasCredentials":obj.has_credentials})
        return obj


def test_connection(*, connection_id, tenant_id:int, actor_user_id:int|None):
    with transaction.atomic():
        obj=IntegrationConnection.objects.select_for_update().get(pk=connection_id,tenant_id=tenant_id)
        try:
            secrets=decrypt_secret_payload(obj.secret_ciphertext)
            result=probe(category=obj.category,adapter_code=obj.adapter_code,base_url=obj.base_url,config=obj.config_json or {},secrets=secrets)
            status=result["status"]; summary=result["summary"]
            obj.status=IntegrationConnection.Status.VERIFIED if status=="VERIFIED" else IntegrationConnection.Status.CONFIGURED
            obj.last_test_status=status;obj.last_test_message=summary
        except Exception as exc:
            code=getattr(exc,"code","PROBE_FAILED");status="ERROR";summary=str(exc)[:255]
            result={"status":"ERROR","code":code}
            obj.status=IntegrationConnection.Status.ERROR;obj.last_test_status=code;obj.last_test_message=summary
        obj.last_test_at=timezone.now();obj.updated_by=actor_user_id;obj.save(update_fields=["status","last_test_at","last_test_status","last_test_message","updated_by","updated_at"])
        IntegrationTestRun.objects.create(tenant_id=tenant_id,connection=obj,adapter_code=obj.adapter_code,status=status,summary=summary,detail_json=result,tested_by=actor_user_id)
        _audit(tenant_id=tenant_id,actor_user_id=actor_user_id,event_type="CONNECTION_TESTED",connection_code=obj.code,summary=summary,payload={"status":status,"adapter":obj.adapter_code})
        return status,result


def connection_contract(*, tenant_id:int, category:str, code:str|None=None) -> dict|None:
    qs=IntegrationConnection.objects.filter(tenant_id=tenant_id,category=category,enabled=True,status__in=[IntegrationConnection.Status.CONFIGURED,IntegrationConnection.Status.VERIFIED])
    if code: qs=qs.filter(code=code)
    obj=qs.order_by("code").first()
    if not obj: return None
    mappings=[]
    for profile in obj.mapping_profiles.filter(enabled=True).prefetch_related("fields"):
        mappings.append({"code":profile.code,"name":profile.name,"direction":profile.direction,"sourceObject":profile.source_object,"targetDomain":profile.target_domain,"fields":[{"source":f.source_field,"target":f.target_field,"transform":f.transform_code,"required":f.required,"default":f.default_value} for f in profile.fields.all()]})
    payload={"schemaVersion":"hr.integration.v1","connection":{"code":obj.code,"category":obj.category,"adapterCode":obj.adapter_code,"baseUrl":obj.base_url,"config":obj.config_json,"status":obj.status},"mappings":mappings}
    payload["contractHash"]=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    return payload
