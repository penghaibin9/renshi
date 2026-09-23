from __future__ import annotations

import json
from django import forms

from .models import (
    ApprovalRoleRule, ConditionRule, ExcelColumn, ExcelTemplate, FieldDefinition,
    FormDefinition, NotificationRule, PrintTemplate, WorkflowStage,
)
from .services import SUPPORTED_DOMAINS, normalize_code


class StyledFormMixin:
    def _style(self):
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (css + " hrcfg-input").strip()


class WorkflowCreateForm(StyledFormMixin, forms.Form):
    code = forms.CharField(label="流程编码", max_length=64, help_text="例如 RECRUITMENT_APPROVAL")
    name = forms.CharField(label="流程名称", max_length=160)
    business_domain = forms.ChoiceField(label="所属模块", choices=[(x, x) for x in SUPPORTED_DOMAINS])
    description = forms.CharField(label="用途说明", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); self._style()

    def clean_code(self):
        return normalize_code(self.cleaned_data["code"])


class BaseVersionModelForm(StyledFormMixin, forms.ModelForm):
    def __init__(self, *args, version=None, **kwargs):
        self.version = version
        super().__init__(*args, **kwargs)
        if version is not None:
            # Bind the server-resolved school/version before ModelForm._post_clean().
            # tenant_id is never accepted from browser input.
            self.instance.version = version
            self.instance.tenant_id = version.tenant_id
        self._style()

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.version is not None:
            obj.version = self.version
            obj.tenant_id = self.version.tenant_id
        if commit:
            obj.full_clean()
            obj.save()
        return obj


class StageForm(BaseVersionModelForm):
    class Meta:
        model = WorkflowStage
        fields = ("code", "name", "sort_order", "is_start", "is_end")
        labels = {"code":"阶段编码","name":"阶段名称","sort_order":"顺序","is_start":"开始阶段","is_end":"结束阶段"}

    def clean_code(self): return normalize_code(self.cleaned_data["code"])


class FormDefinitionForm(BaseVersionModelForm):
    class Meta:
        model = FormDefinition
        fields = ("code", "title", "stage_code", "sort_order", "description")
        labels = {"code":"表单编码","title":"表单名称","stage_code":"所属阶段编码","sort_order":"顺序","description":"说明"}

    def clean_code(self): return normalize_code(self.cleaned_data["code"])


class FieldDefinitionForm(BaseVersionModelForm):
    options_text = forms.CharField(label="选项", required=False, help_text="下拉/多选时每行一个选项", widget=forms.Textarea(attrs={"rows":3}))
    validation_text = forms.CharField(label="高级校验 JSON", required=False, widget=forms.Textarea(attrs={"rows":3}))

    class Meta:
        model = FieldDefinition
        fields = ("form", "key", "label", "field_type", "required", "sort_order", "help_text", "default_value")
        labels = {"form":"所属表单","key":"字段编码","label":"字段名称","field_type":"字段类型","required":"必填","sort_order":"顺序","help_text":"填写提示","default_value":"默认值"}

    def __init__(self, *args, version=None, **kwargs):
        super().__init__(*args, version=version, **kwargs)
        if version is not None:
            self.fields["form"].queryset = FormDefinition.objects.filter(version=version).order_by("sort_order")
        if self.instance and self.instance.pk:
            self.fields["options_text"].initial = "\n".join(str(x) for x in (self.instance.options_json or []))
            self.fields["validation_text"].initial = json.dumps(self.instance.validation_json or {}, ensure_ascii=False, indent=2)

    def clean_key(self): return normalize_code(self.cleaned_data["key"])

    def clean_validation_text(self):
        raw = (self.cleaned_data.get("validation_text") or "").strip()
        if not raw: return {}
        try: value = json.loads(raw)
        except json.JSONDecodeError as exc: raise forms.ValidationError("高级校验必须是合法 JSON") from exc
        if not isinstance(value, dict): raise forms.ValidationError("高级校验 JSON 必须是对象")
        return value

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.options_json = [x.strip() for x in (self.cleaned_data.get("options_text") or "").splitlines() if x.strip()]
        obj.validation_json = self.cleaned_data.get("validation_text") or {}
        if commit:
            obj.full_clean(); obj.save()
        return obj


class ApprovalRoleForm(BaseVersionModelForm):
    class Meta:
        model = ApprovalRoleRule
        fields = ("code", "stage_code", "role_code", "role_name", "data_scope", "sort_order", "approval_mode")
        labels = {"code":"规则编码","stage_code":"审批阶段","role_code":"角色编码","role_name":"角色名称","data_scope":"数据范围","sort_order":"顺序","approval_mode":"通过规则"}
    def clean_code(self): return normalize_code(self.cleaned_data["code"])


class ConditionRuleForm(BaseVersionModelForm):
    compare_value_text = forms.CharField(label="比较值", required=False, help_text="多个值用逗号分隔")
    class Meta:
        model = ConditionRule
        fields = ("code", "name", "source_stage_code", "field_key", "operator", "target_stage_code", "priority")
        labels = {"code":"条件编码","name":"条件名称","source_stage_code":"来源阶段","field_key":"判断字段","operator":"运算符","target_stage_code":"满足后进入阶段","priority":"优先级"}
    def __init__(self,*args,version=None,**kwargs):
        super().__init__(*args,version=version,**kwargs)
        if self.instance and self.instance.pk:
            value=self.instance.compare_value_json
            if isinstance(value,list): self.fields["compare_value_text"].initial=",".join(map(str,value))
            elif isinstance(value,dict) and "value" in value: self.fields["compare_value_text"].initial=str(value["value"])
    def clean_code(self): return normalize_code(self.cleaned_data["code"])
    def save(self,commit=True):
        obj=super().save(commit=False); raw=(self.cleaned_data.get("compare_value_text") or "").strip()
        obj.compare_value_json=[x.strip() for x in raw.split(",") if x.strip()] if "," in raw else ({"value":raw} if raw else {})
        if commit: obj.full_clean(); obj.save()
        return obj


class NotificationRuleForm(BaseVersionModelForm):
    class Meta:
        model=NotificationRule
        fields=("code","event_code","channel","recipient_role_code","subject_template","body_template","enabled")
        labels={"code":"规则编码","event_code":"触发事件","channel":"通知渠道","recipient_role_code":"接收角色","subject_template":"标题模板","body_template":"正文模板","enabled":"启用"}
        widgets={"body_template":forms.Textarea(attrs={"rows":4})}
    def clean_code(self): return normalize_code(self.cleaned_data["code"])


class PrintTemplateForm(BaseVersionModelForm):
    class Meta:
        model=PrintTemplate
        fields=("code","name","output_format","template_body","enabled")
        labels={"code":"模板编码","name":"模板名称","output_format":"输出格式","template_body":"模板正文","enabled":"启用"}
        widgets={"template_body":forms.Textarea(attrs={"rows":8,"placeholder":"支持 {{ FIELD_CODE }} 占位符"})}
    def clean_code(self): return normalize_code(self.cleaned_data["code"])


class ExcelTemplateForm(BaseVersionModelForm):
    class Meta:
        model=ExcelTemplate
        fields=("code","name","direction","sheet_name","enabled")
        labels={"code":"模板编码","name":"模板名称","direction":"用途","sheet_name":"工作表名称","enabled":"启用"}
    def clean_code(self): return normalize_code(self.cleaned_data["code"])


class ExcelColumnForm(BaseVersionModelForm):
    class Meta:
        model=ExcelColumn
        fields=("template","field_key","header","sort_order","required","data_type","example_value")
        labels={"template":"Excel模板","field_key":"对应字段编码","header":"列标题","sort_order":"顺序","required":"必填","data_type":"数据类型","example_value":"示例值"}
    def __init__(self,*args,version=None,**kwargs):
        super().__init__(*args,version=version,**kwargs)
        if version is not None: self.fields["template"].queryset=ExcelTemplate.objects.filter(version=version).order_by("code")
    def clean_field_key(self): return normalize_code(self.cleaned_data["field_key"])
