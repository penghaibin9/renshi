from __future__ import annotations

import json
from django import forms

from .adapters import AdapterError, catalog, get_spec
from .models import IntegrationConnection, IntegrationFieldMapping, IntegrationMappingProfile


class StyledFormMixin:
    def _style(self):
        for f in self.fields.values():
            f.widget.attrs["class"]=(f.widget.attrs.get("class","")+" hrcfg-input").strip()


class TenantBoundModelForm(StyledFormMixin, forms.ModelForm):
    def __init__(self, *args, tenant_id=None, **kwargs):
        self.tenant_id = tenant_id
        super().__init__(*args, **kwargs)
        if tenant_id is not None:
            # Server-resolved tenant only; never trust a posted tenant id.
            self.instance.tenant_id = tenant_id
        self._style()


class ConnectionForm(TenantBoundModelForm):
    config_text=forms.CharField(label="非敏感配置 JSON",required=False,widget=forms.Textarea(attrs={"rows":6}),help_text='例如 {"health_path":"/health"}。不会存密码。')
    credential_text=forms.CharField(label="密钥 JSON（只写不回显）",required=False,widget=forms.PasswordInput(render_value=False),help_text='例如 {"client_secret":"..."}；保存后页面不回显。')

    class Meta:
        model=IntegrationConnection
        fields=("code","name","category","adapter_code","base_url","enabled")
        labels={"code":"连接编码","name":"连接名称","category":"接口类别","adapter_code":"适配器（Adapter）","base_url":"系统根地址（Base URL）","enabled":"启用"}

    def __init__(self,*args,tenant_id=None,**kwargs):
        super().__init__(*args,tenant_id=tenant_id,**kwargs)
        self.fields["adapter_code"].widget=forms.Select(choices=[(x.code,f"{x.name} · {x.code}") for x in catalog()]);self._style()
        if self.instance and self.instance.pk:
            self.fields["config_text"].initial=json.dumps(self.instance.config_json or {},ensure_ascii=False,indent=2)
            self.fields["credential_text"].help_text="已有密钥" if self.instance.has_credentials else self.fields["credential_text"].help_text

    def clean_code(self):
        code=str(self.cleaned_data["code"]).strip().upper().replace("-","_").replace(" ","_")
        if not code.replace("_","").isalnum() or not code[0].isalpha(): raise forms.ValidationError("编码只能使用字母、数字、下划线，并以字母开头")
        return code

    def clean_config_text(self):
        raw=(self.cleaned_data.get("config_text") or "").strip()
        if not raw:return {}
        try:value=json.loads(raw)
        except json.JSONDecodeError as exc:raise forms.ValidationError("配置必须是合法 JSON") from exc
        if not isinstance(value,dict):raise forms.ValidationError("配置 JSON 必须是对象")
        return value

    def clean_credential_text(self):
        raw=(self.cleaned_data.get("credential_text") or "").strip()
        if not raw:return {}
        try:value=json.loads(raw)
        except json.JSONDecodeError as exc:raise forms.ValidationError("密钥必须是合法 JSON") from exc
        if not isinstance(value,dict):raise forms.ValidationError("密钥 JSON 必须是对象")
        return value

    def clean(self):
        data=super().clean()
        if data.get("category") and data.get("adapter_code"):
            try:
                spec=get_spec(data["adapter_code"])
            except AdapterError as exc:
                self.add_error("adapter_code", str(exc))
                return data
            if spec.category!=data["category"]:
                self.add_error("adapter_code",f"该 Adapter 属于 {spec.category}")
        return data


class MappingProfileForm(TenantBoundModelForm):
    class Meta:
        model=IntegrationMappingProfile
        fields=("code","name","direction","source_object","target_domain","enabled")
        labels={"code":"映射编码","name":"映射名称","direction":"方向","source_object":"外部对象","target_domain":"人事目标域","enabled":"启用"}
    def __init__(self,*args,tenant_id=None,connection=None,**kwargs):
        super().__init__(*args,tenant_id=tenant_id,**kwargs)
        if connection is not None:
            self.instance.connection=connection
    def clean_code(self):return str(self.cleaned_data["code"]).strip().upper().replace("-","_").replace(" ","_")


class FieldMappingForm(TenantBoundModelForm):
    class Meta:
        model=IntegrationFieldMapping
        fields=("source_field","target_field","transform_code","required","default_value","sort_order")
        labels={"source_field":"外部字段","target_field":"人事字段","transform_code":"转换规则","required":"必填","default_value":"默认值","sort_order":"顺序"}
    def __init__(self,*args,tenant_id=None,profile=None,**kwargs):
        super().__init__(*args,tenant_id=tenant_id,**kwargs)
        if profile is not None:
            self.instance.profile=profile


class SsoIdentityPrebindForm(StyledFormMixin, forms.Form):
    staff_no = forms.CharField(label="HR03 工号", max_length=64)
    external_subject = forms.CharField(label="学校统一认证 Subject", max_length=254, widget=forms.PasswordInput(render_value=False), help_text="只用于建立身份绑定；页面和审计日志不回显原值。")
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self._style()
