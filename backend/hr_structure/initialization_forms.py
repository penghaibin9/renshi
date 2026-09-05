"""Explicit school-confirmed initial organization and first vacant position."""

from decimal import Decimal

from django import forms


class InitialStructureForm(forms.Form):
    root_code = forms.RegexField(r"^[A-Za-z0-9_-]+$", max_length=64, label="学校组织编码")
    department_code = forms.RegexField(r"^[A-Za-z0-9_-]+$", max_length=64, label="首个部门编码")
    department_name = forms.CharField(max_length=200, label="首个部门名称")
    department_type = forms.ChoiceField(
        choices=(("DEPARTMENT", "系部"), ("COLLEGE", "学院"), ("OFFICE", "职能部门")),
        label="部门类型",
    )
    catalog_code = forms.RegexField(r"^[A-Za-z0-9_-]+$", max_length=64, label="岗位目录编码")
    catalog_name = forms.CharField(max_length=200, label="岗位名称")
    category = forms.ChoiceField(
        choices=(("", "请选择岗位类别"), ("MANAGEMENT", "管理岗位"),
                 ("PROFESSIONAL_TECHNICAL", "专业技术岗位"), ("SKILLED_WORKER", "工勤技能岗位"),
                 ("SPECIAL", "特设岗位")),
        label="岗位类别",
    )
    position_code = forms.RegexField(r"^[A-Za-z0-9_-]+$", max_length=64, label="首个岗位编码")
    planned_fte = forms.DecimalField(
        max_digits=3, decimal_places=2, min_value=Decimal("0.01"), max_value=Decimal("1.00"),
        initial=Decimal("1.00"), label="该岗位工作量",
        help_text="1.00 为一个全时岗位。本入口建立一个空缺岗位，不分配人员，不代替编制方案审批。",
    )
    confirmed = forms.BooleanField(
        label="我已核对本校组织及岗位信息，确认将其建立为今日生效的初始记录。"
    )

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", "structure-setup-%s")
        super().__init__(*args, **kwargs)
        for name in ("root_code", "department_code", "catalog_code", "position_code"):
            self.fields[name].help_text = "使用字母、数字、下划线或连字符，正式建立后作为稳定编码。"

    def clean(self):
        data = super().clean()
        for name in ("root_code", "department_code", "catalog_code", "position_code"):
            if name in data:
                data[name] = data[name].upper()
        if data.get("root_code") and data.get("root_code") == data.get("department_code"):
            self.add_error("department_code", "部门编码不能与学校组织编码相同。")
        return data
