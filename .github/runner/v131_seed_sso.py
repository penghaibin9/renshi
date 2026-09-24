from datetime import timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone

from hr_staff.models import HrPerson, HrStaffMaster, HrEmploymentRelationship, HrAccountLink
from hr_integration.models import IntegrationConnection
from hr_integration.crypto import encrypt_secret_payload
from hr_integration.sso_runtime import prebind_identity

tenant_id = 1
user = get_user_model().objects.get(username="ci-admin")

person = HrPerson.objects.create(
    tenant_id=tenant_id,
    legal_name="CI SSO Auditor",
)
staff = HrStaffMaster.objects.create(
    tenant_id=tenant_id,
    person_id=person,
    staff_no="V1-AUDITOR-001",
)
HrEmploymentRelationship.objects.create(
    tenant_id=tenant_id,
    staff_id=staff,
    effective_from=timezone.localdate() - timedelta(days=1),
    status="ACTIVE",
)
HrAccountLink.objects.create(
    tenant_id=tenant_id,
    staff_id=staff,
    auth_user_id=user.pk,
    auth_identifier=user.username,
    link_status=HrAccountLink.LinkStatus.ACTIVE,
    linked_at=timezone.now(),
)

connection = IntegrationConnection.objects.create(
    tenant_id=tenant_id,
    code="SSO_CI_OIDC",
    name="CI OIDC 统一认证",
    category=IntegrationConnection.Category.SSO,
    adapter_code="SSO_OIDC",
    base_url="http://localhost:9012",
    enabled=True,
    status=IntegrationConnection.Status.CONFIGURED,
    config_json={
        "client_id": "hr-ci-oidc",
        "discovery_path": "/.well-known/openid-configuration",
        "subject_claim": "sub",
        "staff_no_claim": "employee_no",
        "scope": "openid profile email",
        "token_auth_method": "client_secret_post",
        "allow_first_login_binding": False,
    },
    secret_ciphertext=encrypt_secret_payload({"client_secret": "hr-ci-oidc-secret"}),
    credential_updated_at=timezone.now(),
)
print(prebind_identity(
    connection,
    staff_no="V1-AUDITOR-001",
    external_subject="ci-subject-v1-auditor",
    actor_user_id=user.pk,
))
