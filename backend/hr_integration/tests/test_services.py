from cryptography.fernet import Fernet
from django.test import TestCase, override_settings

from hr_integration.forms import ConnectionForm, MappingProfileForm
from hr_integration.models import IntegrationAuditEvent, IntegrationConnection, IntegrationTestRun
from hr_integration.services import IntegrationError, connection_contract, save_connection


@override_settings(FIELD_ENCRYPTION_KEYS="test:"+Fernet.generate_key().decode("ascii"))
class IntegrationServiceTests(TestCase):
    def test_secret_is_encrypted_and_never_returned_in_contract(self):
        obj=save_connection(tenant_id=9,actor_user_id=2,instance=None,code="MASTER",name="主数据",category="MASTER_DATA",adapter_code="MASTERDATA_HTTP_JSON",base_url="https://example.edu.cn",enabled=True,config={"health_path":"/health"},secrets={"token":"TOP-SECRET"})
        self.assertNotIn("TOP-SECRET",obj.secret_ciphertext)
        payload=connection_contract(tenant_id=9,category="MASTER_DATA",code="MASTER")
        self.assertNotIn("secret",str(payload).lower())
        self.assertEqual(payload["connection"]["adapterCode"],"MASTERDATA_HTTP_JSON")

    def test_enabled_connection_requires_credentials_when_adapter_requires_them(self):
        with self.assertRaises(IntegrationError):
            save_connection(tenant_id=9,actor_user_id=2,instance=None,code="NOSECRET",name="主数据",category="MASTER_DATA",adapter_code="MASTERDATA_HTTP_JSON",base_url="https://example.edu.cn",enabled=True,config={"health_path":"/health"},secrets={})


    def test_existing_secret_is_reused_on_edit_without_browser_echo(self):
        obj=save_connection(tenant_id=9,actor_user_id=2,instance=None,code="EDITABLE",name="主数据",category="MASTER_DATA",adapter_code="MASTERDATA_HTTP_JSON",base_url="https://example.edu.cn",enabled=True,config={"health_path":"/health"},secrets={"token":"ORIGINAL"})
        original_cipher=obj.secret_ciphertext
        updated=save_connection(tenant_id=9,actor_user_id=3,instance=obj,code="EDITABLE",name="主数据新版",category="MASTER_DATA",adapter_code="MASTERDATA_HTTP_JSON",base_url="https://example.edu.cn",enabled=True,config={"health_path":"/ready"},secrets={})
        self.assertEqual(updated.secret_ciphertext,original_cipher)
        self.assertEqual(updated.name,"主数据新版")

    def test_wrong_secret_shape_cannot_enable_connection(self):
        with self.assertRaises(IntegrationError) as ctx:
            save_connection(tenant_id=9,actor_user_id=2,instance=None,code="BADKEY",name="主数据",category="MASTER_DATA",adapter_code="MASTERDATA_HTTP_JSON",base_url="https://example.edu.cn",enabled=True,config={"health_path":"/health"},secrets={"wrong":"x"})
        self.assertEqual(ctx.exception.code,"CREDENTIAL_REQUIRED")

    def test_unknown_adapter_is_form_error_not_server_exception(self):
        form=ConnectionForm(tenant_id=9,data={"code":"BAD","name":"坏连接","category":"SSO","adapter_code":"NOT_REAL","base_url":"https://example.edu.cn","enabled":""})
        self.assertFalse(form.is_valid())
        self.assertIn("adapter_code",form.errors)

    def test_mapping_profile_form_is_tenant_bound_before_model_validation(self):
        obj=save_connection(tenant_id=9,actor_user_id=2,instance=None,code="MAPBASE",name="主数据",category="MASTER_DATA",adapter_code="MASTERDATA_HTTP_JSON",base_url="https://example.edu.cn",enabled=False,config={"health_path":"/health"},secrets={})
        form=MappingProfileForm(tenant_id=9,connection=obj,prefix="profile",data={"profile-code":"STAFF","profile-name":"人员映射","profile-direction":"INBOUND","profile-source_object":"staff","profile-target_domain":"HR03","profile-enabled":"on"})
        self.assertTrue(form.is_valid(),form.errors)


    def test_switching_adapter_does_not_silently_reuse_old_protocol_secret(self):
        obj=save_connection(tenant_id=9,actor_user_id=2,instance=None,code="SSO",name="学校认证",category="SSO",adapter_code="SSO_OAUTH2",base_url="https://sso.example.edu.cn",enabled=True,config={"authorize_path":"/authorize","token_path":"/token","userinfo_path":"/userinfo","client_id":"old-client","subject_claim":"sub","staff_no_claim":"employee_no"},secrets={"client_secret":"OLD-SECRET"})
        original_cipher=obj.secret_ciphertext
        updated=save_connection(tenant_id=9,actor_user_id=3,instance=obj,code="SSO",name="学校认证",category="SSO",adapter_code="SSO_OIDC",base_url="https://sso.example.edu.cn",enabled=False,config={"client_id":"new-client","staff_no_claim":"employee_no"},secrets={})
        self.assertNotEqual(original_cipher, "")
        self.assertEqual(updated.secret_ciphertext, "")
        self.assertFalse(updated.has_credentials)

    def test_audit_and_test_evidence_are_queryset_append_only(self):
        obj=save_connection(tenant_id=9,actor_user_id=2,instance=None,code="MASTER_AUDIT",name="主数据",category="MASTER_DATA",adapter_code="MASTERDATA_HTTP_JSON",base_url="https://example.edu.cn",enabled=False,config={"health_path":"/health"},secrets={"token":"SECRET"})
        event=IntegrationAuditEvent.objects.filter(tenant_id=9).first()
        self.assertIsNotNone(event)
        with self.assertRaises(ValueError):
            IntegrationAuditEvent.objects.filter(pk=event.pk).update(summary="篡改")
        run=IntegrationTestRun.objects.create(tenant_id=9,connection=obj,adapter_code=obj.adapter_code,status="CONFIG_VALIDATED",summary="证据",detail_json={})
        with self.assertRaises(ValueError):
            IntegrationTestRun.objects.filter(pk=run.pk).delete()
