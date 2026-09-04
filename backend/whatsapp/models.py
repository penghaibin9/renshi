from django.db import models
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from base.encrypted_fields import EncryptedTextField
from base.horilla_company_manager import HorillaCompanyManager
from base.models import Company
from horilla.models import HorillaModel
from horilla_views.cbv_methods import render_template


class WhatsappCredientials(HorillaModel):
    meta_token = EncryptedTextField()
    meta_business_id = models.CharField(max_length=255)
    meta_phone_number_id = models.CharField(max_length=255)
    meta_phone_number = models.CharField(max_length=20)
    created_templates = models.BooleanField(default=False)
    meta_webhook_token = EncryptedTextField(
        verbose_name="Webhook Token",
        help_text=_("This token is used to connect webhook to the server"),
    )
    meta_app_secret = EncryptedTextField(
        null=True,
        blank=True,
        verbose_name="Meta App Secret",
        help_text=_("Required to verify signed webhook requests"),
    )
    company_id = models.ManyToManyField(Company, blank=True, verbose_name="Company")
    is_primary = models.BooleanField(default=False)

    objects = HorillaCompanyManager()

    def __str__(self):
        return f"WhatsApp Business {self.meta_business_id} ({self.meta_phone_number})"

    def token_render(self):
        return format_html(
            '<span title="{}">{}</span>',
            _("Credential is encrypted and cannot be displayed"),
            _("Stored securely"),
        )

    def get_update_url(self):
        url = reverse("whatsapp-credential-update", kwargs={"pk": self.pk})
        return url

    def get_publish_button(self):
        html = render_template(
            path="whatsapp/option_buttons.html", context={"instance": self}
        )
        return html

    def get_primary(self):
        if self.is_primary:
            return "class='bg-primary-50'"

    def get_instance(self):
        """
        used to return the id of the instance
        Returns:
            id of the instance
        """
        return self.pk

    def get_delete_url(self):
        url = reverse("whatsapp-credential-delete")
        id = self.pk
        url = f"{url}?id={id}"
        return url

    def get_test_message_url(self):
        url = reverse("send-test-message")
        return url

    def get_webhook_token(self):
        return format_html(
            '<span title="{}">{}</span>',
            _("Credential is encrypted and cannot be displayed"),
            _("Stored securely"),
        )


class WhatsappFlowDetails(models.Model):
    template = models.CharField(max_length=50)
    flow_id = models.CharField(max_length=50)
    whatsapp_id = models.ForeignKey(WhatsappCredientials, on_delete=models.CASCADE)

    def __str__(self) -> str:
        return self.template
