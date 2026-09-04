# forms.py
from typing import Any

from django import forms
from django.forms import ValidationError
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _

from base.forms import ModelForm
from whatsapp.models import WhatsappCredientials


class WhatsappForm(ModelForm):
    cols = {"meta_token": 12}

    class Meta:
        model = WhatsappCredientials
        fields = "__all__"
        exclude = ["is_active", "created_templates"]

    def as_p(self):
        """
        Render the form fields as HTML table rows with Bootstrap styling.
        """
        context = {"form": self}
        table_html = render_to_string("horilla_form.html", context)
        return table_html

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ("meta_token", "meta_webhook_token", "meta_app_secret"):
            field = self.fields[field_name]
            field.widget = forms.PasswordInput(render_value=False)
            field.required = self.instance.pk is None
        if self.instance.pk:
            self.fields["meta_app_secret"].help_text = _(
                "留空表示保留当前应用密钥；填写新值将立即轮换。"
            )

    def clean(self):
        cleaned_data = super().clean()
        secret_fields = ("meta_token", "meta_webhook_token", "meta_app_secret")
        if self.instance.pk:
            stored = WhatsappCredientials._base_manager.get(pk=self.instance.pk)
            for field_name in secret_fields:
                if not cleaned_data.get(field_name):
                    cleaned_data[field_name] = getattr(stored, field_name)
        else:
            for field_name in secret_fields:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, _("此安全凭据为必填项。"))
        companies = cleaned_data.get("company_id")
        is_primary = cleaned_data.get("is_primary")

        if companies:
            for company in companies:
                existing_primary = WhatsappCredientials.objects.filter(
                    company_id=company, is_primary=True
                ).exclude(id=self.instance.id)

                if is_primary:
                    if existing_primary.exists():
                        raise ValidationError(
                            f"Company '{company.company}' already has a primary credential."
                        )
                else:
                    if not existing_primary.exists():
                        cleaned_data["is_primary"] = True

        return cleaned_data
