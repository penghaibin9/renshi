import base64
from types import SimpleNamespace

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.test import SimpleTestCase, override_settings

from base.encrypted_fields import (
    ENCRYPTED_PREFIX,
    EncryptedTextField,
    decrypt_value,
    encrypt_value,
    rotate_encrypted_value,
)
from base.forms import ModelForm
from horilla_api.api_serializers.recruitment.serializers import (
    LinkedInAccountSerializer,
)
from horilla_meet.models import GoogleCloudCredential
from recruitment.models import LinkedInAccount
from whatsapp.models import WhatsappCredientials


OLD_KEY = base64.urlsafe_b64encode(b"o" * 32).decode("ascii")
NEW_KEY = base64.urlsafe_b64encode(b"n" * 32).decode("ascii")


class CredentialFormModel(models.Model):
    credential = EncryptedTextField()

    class Meta:
        app_label = "base"
        managed = False


class CredentialModelForm(ModelForm):
    class Meta:
        model = CredentialFormModel
        fields = ["credential"]


class EncryptedCredentialPrimitiveTests(SimpleTestCase):
    @override_settings(
        FIELD_ENCRYPTION_KEYS=f"2026:{OLD_KEY}",
        SECRET_KEY="independent-django-test-key",
    )
    def test_round_trip_uses_authenticated_envelope(self):
        stored = encrypt_value("smtp-password")

        self.assertTrue(stored.startswith(f"{ENCRYPTED_PREFIX}2026:"))
        self.assertNotIn("smtp-password", stored)
        self.assertEqual(decrypt_value(stored), "smtp-password")

    @override_settings(
        FIELD_ENCRYPTION_KEYS=f"2026:{OLD_KEY}",
        SECRET_KEY="independent-django-test-key",
    )
    def test_tampered_ciphertext_fails_closed(self):
        stored = encrypt_value("api-secret")
        tampered = stored[:-1] + ("A" if stored[-1] != "A" else "B")

        with self.assertRaisesMessage(
            ImproperlyConfigured, "integrity verification"
        ):
            decrypt_value(tampered)

    def test_legacy_plaintext_is_read_only_compatible(self):
        self.assertEqual(decrypt_value("legacy-plaintext"), "legacy-plaintext")

    def test_old_key_can_be_read_and_rotated_to_current_key(self):
        with override_settings(
            FIELD_ENCRYPTION_KEYS=f"2026:{OLD_KEY}",
            SECRET_KEY="independent-django-test-key",
        ):
            old_value = encrypt_value("rotate-me")

        with override_settings(
            FIELD_ENCRYPTION_KEYS=f"2027:{NEW_KEY},2026:{OLD_KEY}",
            SECRET_KEY="independent-django-test-key",
        ):
            rotated = rotate_encrypted_value(old_value)
            self.assertTrue(rotated.startswith(f"{ENCRYPTED_PREFIX}2027:"))
            self.assertEqual(decrypt_value(rotated), "rotate-me")

    @override_settings(
        FIELD_ENCRYPTION_KEYS=f"2027:{NEW_KEY}",
        SECRET_KEY="independent-django-test-key",
    )
    def test_missing_historical_key_fails_closed(self):
        unknown = f"{ENCRYPTED_PREFIX}2026:gAAAAABinvalid"
        with self.assertRaisesMessage(ImproperlyConfigured, "unavailable key"):
            decrypt_value(unknown)

    @override_settings(
        FIELD_ENCRYPTION_KEYS=f"2026:{OLD_KEY}",
        SECRET_KEY="independent-django-test-key",
    )
    def test_model_field_encrypts_database_and_serialized_values(self):
        field = EncryptedTextField()
        field.set_attributes_from_name("credential")

        prepared = field.get_prep_value("database-secret")
        serialized = field.value_to_string(
            SimpleNamespace(credential="database-secret")
        )

        self.assertNotIn("database-secret", prepared)
        self.assertNotIn("database-secret", serialized)
        self.assertEqual(field.from_db_value(prepared, None, None), "database-secret")

    def test_model_form_never_renders_existing_secret_and_preserves_blank_edit(self):
        instance = CredentialFormModel(pk=7, credential="existing-secret")
        unbound = CredentialModelForm(instance=instance)
        self.assertNotIn("existing-secret", unbound.as_p())
        self.assertEqual(unbound.fields["credential"].widget.input_type, "password")

        bound = CredentialModelForm({"credential": ""}, instance=instance)
        self.assertTrue(bound.is_valid(), bound.errors)
        self.assertEqual(bound.cleaned_data["credential"], "existing-secret")

    def test_model_form_requires_secret_when_creating(self):
        form = CredentialModelForm({"credential": ""})
        self.assertFalse(form.is_valid())
        self.assertIn("credential", form.errors)

    def test_credential_display_helpers_never_embed_plaintext(self):
        whatsapp = WhatsappCredientials(
            meta_token="whatsapp-secret",
            meta_webhook_token="webhook-secret",
        )
        google = GoogleCloudCredential(client_secret="google-secret")

        rendered = " ".join(
            (
                str(whatsapp.token_render()),
                str(whatsapp.get_webhook_token()),
                str(google.get_client_secret_col()),
            )
        )
        self.assertNotIn("whatsapp-secret", rendered)
        self.assertNotIn("webhook-secret", rendered)
        self.assertNotIn("google-secret", rendered)

    def test_linkedin_api_token_is_write_only(self):
        serializer = LinkedInAccountSerializer(
            instance=LinkedInAccount(
                id=1,
                username="app",
                email="owner@university.edu",
                api_token="linkedin-secret",
                sub_id="subject",
                company_id=None,
                is_active=True,
            )
        )
        self.assertNotIn("api_token", serializer.data)
